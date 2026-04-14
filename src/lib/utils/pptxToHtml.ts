/**
 * Lightweight PPTX → Image renderer.
 *
 * Extracts text and images from each slide and renders them
 * directly to canvas, returning PNG data URLs.
 *
 * Uses jszip (dynamically imported) and the browser Canvas 2D API.
 * No theme resolution, charts, SmartArt, or animations — preview only.
 *
 * OOXML uses XML namespaces; we resolve elements via getElementsByTagNameNS
 * so previews work across browsers (prefix-only lookups often fail).
 */

const EMU_PER_PX = 9525;
const emuToPx = (emu: number) => Math.round(emu / EMU_PER_PX);

const parseEmu = (val: string | null | undefined): number => (val ? parseInt(val, 10) || 0 : 0);

const NS_PML = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const NS_DML = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const NS_REL_PKG = 'http://schemas.openxmlformats.org/package/2006/relationships';
const NS_REL_OFFICE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';

const MAX_CANVAS_DIM = 4096;

const clampDim = (w: number, h: number): { w: number; h: number } => {
	let cw = Number.isFinite(w) && w > 0 ? w : 960;
	let ch = Number.isFinite(h) && h > 0 ? h : 540;
	cw = Math.min(Math.max(Math.round(cw), 320), MAX_CANVAS_DIM);
	ch = Math.min(Math.max(Math.round(ch), 240), MAX_CANVAS_DIM);
	return { w: cw, h: ch };
};

/** Load a data URI into an Image element and wait for it. */
const loadImage = (src: string): Promise<HTMLImageElement> =>
	new Promise((resolve, reject) => {
		const img = new Image();
		img.onload = () => resolve(img);
		img.onerror = () => reject(new Error('Failed to load image'));
		img.src = src;
	});

function blipEmbedId(blip: Element): string {
	return (
		blip.getAttributeNS(NS_REL_OFFICE, 'embed') ||
		blip.getAttribute('r:embed') ||
		blip.getAttribute('embed') ||
		''
	);
}

/**
 * Convert PPTX ArrayBuffer → array of PNG data URL strings, one per slide.
 */
export async function pptxToImages(
	buffer: ArrayBuffer
): Promise<{ images: string[]; width: number; height: number }> {
	if (!buffer || buffer.byteLength < 64) {
		throw new Error('Invalid PPTX: empty or too small');
	}

	const JSZip = (await import('jszip')).default;
	let zip;
	try {
		zip = await JSZip.loadAsync(buffer);
	} catch (e) {
		throw new Error(
			`Invalid PPTX (not a zip): ${e instanceof Error ? e.message : String(e)}`
		);
	}

	// ── Read slide dimensions from presentation.xml ──────────────────
	let slideW = 960;
	let slideH = 540;
	const presXml = zip.file('ppt/presentation.xml');
	if (presXml) {
		const presText = await presXml.async('text');
		const presDoc = new DOMParser().parseFromString(presText, 'application/xml');
		const sldSz =
			presDoc.getElementsByTagNameNS(NS_PML, 'sldSz')[0] ||
			presDoc.getElementsByTagName('p:sldSz')[0];
		if (sldSz) {
			slideW = emuToPx(parseEmu(sldSz.getAttribute('cx')));
			slideH = emuToPx(parseEmu(sldSz.getAttribute('cy')));
		}
	}
	({ w: slideW, h: slideH } = clampDim(slideW, slideH));

	// ── Collect media files (images) as base64 data URIs ─────────────
	const media: Record<string, string> = {};
	const mediaFiles = Object.keys(zip.files).filter((f) => f.startsWith('ppt/media/'));
	await Promise.all(
		mediaFiles.map(async (path) => {
			const file = zip.file(path);
			if (!file) return;
			const base64 = await file.async('base64');
			const ext = path.split('.').pop()?.toLowerCase() ?? '';
			const mime =
				ext === 'png'
					? 'image/png'
					: ext === 'gif'
						? 'image/gif'
						: ext === 'svg'
							? 'image/svg+xml'
							: ext === 'webp'
								? 'image/webp'
								: ext === 'emf' || ext === 'wmf'
									? 'image/x-emf'
									: 'image/jpeg';
			media[path] = `data:${mime};base64,${base64}`;
		})
	);

	// ── Discover slide files ─────────────────────────────────────────
	const slideFiles = Object.keys(zip.files)
		.filter((f) => /^ppt\/slides\/slide\d+\.xml$/i.test(f))
		.sort((a, b) => {
			const na = parseInt(a.match(/slide(\d+)/i)?.[1] ?? '0', 10);
			const nb = parseInt(b.match(/slide(\d+)/i)?.[1] ?? '0', 10);
			return na - nb;
		});

	if (slideFiles.length === 0) {
		throw new Error('Invalid PPTX: no slides found under ppt/slides/');
	}

	const images: string[] = [];

	for (const slidePath of slideFiles) {
		try {
			const slideEntry = zip.file(slidePath);
			if (!slideEntry) continue;
			const slideText = await slideEntry.async('text');
			const slideDoc = new DOMParser().parseFromString(slideText, 'application/xml');

			// Load relationship file for this slide to resolve image references
			const slideNum = slidePath.match(/slide(\d+)/i)?.[1];
			const relsPath = `ppt/slides/_rels/slide${slideNum}.xml.rels`;
			const rels: Record<string, string> = {};
			const relsFile = zip.file(relsPath);
			if (relsFile) {
				const relsText = await relsFile.async('text');
				const relsDoc = new DOMParser().parseFromString(relsText, 'application/xml');
				const relEls = relsDoc.getElementsByTagNameNS(NS_REL_PKG, 'Relationship');
				const list =
					relEls.length > 0 ? relEls : relsDoc.getElementsByTagName('Relationship');
				for (let i = 0; i < list.length; i++) {
					const rel = list[i];
					const id = rel.getAttribute('Id') ?? '';
					const target = rel.getAttribute('Target') ?? '';
					if (!id || !target) continue;
					if (target.startsWith('../')) {
						rels[id] = 'ppt/' + target.replace(/^\.\.\//, '');
					} else {
						rels[id] = target.startsWith('ppt/') ? target : 'ppt/' + target;
					}
				}
			}

			// ── Create canvas and render slide ───────────────────────────
			const canvas = document.createElement('canvas');
			canvas.width = slideW;
			canvas.height = slideH;
			const ctx = canvas.getContext('2d');
			if (!ctx) {
				throw new Error('Canvas 2D context unavailable');
			}

			// White background
			ctx.fillStyle = '#ffffff';
			ctx.fillRect(0, 0, slideW, slideH);

			const spTree =
				slideDoc.getElementsByTagNameNS(NS_PML, 'spTree')[0] ||
				slideDoc.getElementsByTagName('p:spTree')[0];
			if (!spTree) {
				images.push(canvas.toDataURL('image/png'));
				continue;
			}

			const shapes = [
				...Array.from(spTree.getElementsByTagNameNS(NS_PML, 'sp')),
				...Array.from(spTree.getElementsByTagNameNS(NS_PML, 'pic')),
				...Array.from(spTree.getElementsByTagName('p:sp')),
				...Array.from(spTree.getElementsByTagName('p:pic'))
			];

			// Dedupe by reference (fallback lists may overlap)
			const seen = new WeakSet<Element>();
			const uniqShapes = shapes.filter((s) => {
				if (seen.has(s)) return false;
				seen.add(s);
				return true;
			});

			for (const shape of uniqShapes) {
				const xfrm =
					shape.getElementsByTagNameNS(NS_DML, 'xfrm')[0] ||
					shape.getElementsByTagName('a:xfrm')[0] ||
					shape.getElementsByTagName('p:xfrm')[0];
				if (!xfrm) continue;

				const off =
					xfrm.getElementsByTagNameNS(NS_DML, 'off')[0] ||
					xfrm.getElementsByTagName('a:off')[0];
				const extEl =
					xfrm.getElementsByTagNameNS(NS_DML, 'ext')[0] ||
					xfrm.getElementsByTagName('a:ext')[0];
				if (!off || !extEl) continue;

				const x = emuToPx(parseEmu(off.getAttribute('x')));
				const y = emuToPx(parseEmu(off.getAttribute('y')));
				const w = emuToPx(parseEmu(extEl.getAttribute('cx')));
				const h = emuToPx(parseEmu(extEl.getAttribute('cy')));

				if (w === 0 && h === 0) continue;

				// ── Picture ──────────────────────────────────────────────
				const blipFill =
					shape.getElementsByTagNameNS(NS_PML, 'blipFill')[0] ||
					shape.getElementsByTagName('p:blipFill')[0];
				if (blipFill) {
					const blip =
						blipFill.getElementsByTagNameNS(NS_DML, 'blip')[0] ||
						blipFill.getElementsByTagName('a:blip')[0];
					if (blip) {
						const rEmbed = blipEmbedId(blip);
						const mediaPath = rels[rEmbed];
						const dataUri = mediaPath ? media[mediaPath] : '';
						if (dataUri && !dataUri.includes('image/x-emf')) {
							try {
								const img = await loadImage(dataUri);
								ctx.drawImage(img, x, y, w, h);
							} catch {
								// Skip images that fail to load
							}
						}
					}
					continue;
				}

				// ── Text shape ───────────────────────────────────────────
				const txBody =
					shape.getElementsByTagNameNS(NS_PML, 'txBody')[0] ||
					shape.getElementsByTagName('p:txBody')[0];
				if (!txBody) continue;

				ctx.save();
				ctx.rect(x, y, w, h);
				ctx.clip();

				const paragraphs = txBody.getElementsByTagNameNS(NS_DML, 'p');
				const paragraphsFallback = txBody.getElementsByTagName('a:p');
				const paraEls =
					paragraphs.length > 0 ? paragraphs : paragraphsFallback;

				let cursorY = y;
				const defaultFontSize = 12;

				for (let pi = 0; pi < paraEls.length; pi++) {
					const para = paraEls[pi];
					const runs = para.getElementsByTagNameNS(NS_DML, 'r');
					const runsFb = para.getElementsByTagName('a:r');
					const runEls = runs.length > 0 ? runs : runsFb;

					if (runEls.length === 0) {
						cursorY += defaultFontSize * 1.5;
						continue;
					}

					let maxFontPt = defaultFontSize;
					for (let ri = 0; ri < runEls.length; ri++) {
						const rPr =
							runEls[ri].getElementsByTagNameNS(NS_DML, 'rPr')[0] ||
							runEls[ri].getElementsByTagName('a:rPr')[0];
						if (rPr) {
							const sz = rPr.getAttribute('sz');
							if (sz) {
								const pt = parseInt(sz, 10) / 100;
								if (pt > maxFontPt) maxFontPt = pt;
							}
						}
					}

					const lineHeight = maxFontPt * 1.4;
					cursorY += maxFontPt;

					let cursorX = x + 4;

					for (let ri = 0; ri < runEls.length; ri++) {
						const run = runEls[ri];
						const rPr =
							run.getElementsByTagNameNS(NS_DML, 'rPr')[0] ||
							run.getElementsByTagName('a:rPr')[0];
						const tEl =
							run.getElementsByTagNameNS(NS_DML, 't')[0] ||
							run.getElementsByTagName('a:t')[0];
						const text = tEl?.textContent ?? '';
						if (!text) continue;

						let fontPt = defaultFontSize;
						let bold = false;
						let italic = false;
						let color = '#000000';

						if (rPr) {
							if (rPr.getAttribute('b') === '1') bold = true;
							if (rPr.getAttribute('i') === '1') italic = true;
							const sz = rPr.getAttribute('sz');
							if (sz) fontPt = parseInt(sz, 10) / 100;
							const solidFill =
								rPr.getElementsByTagNameNS(NS_DML, 'solidFill')[0] ||
								rPr.getElementsByTagName('a:solidFill')[0];
							if (solidFill) {
								const srgb =
									solidFill.getElementsByTagNameNS(NS_DML, 'srgbClr')[0] ||
									solidFill.getElementsByTagName('a:srgbClr')[0];
								if (srgb) {
									const val = srgb.getAttribute('val');
									if (val) color = `#${val}`;
								}
							}
						}

						ctx.font = `${italic ? 'italic ' : ''}${bold ? 'bold ' : ''}${fontPt}pt Calibri, Arial, sans-serif`;
						ctx.fillStyle = color;
						ctx.textBaseline = 'alphabetic';

						const words = text.split(/(\s+)/);
						for (const word of words) {
							const metrics = ctx.measureText(word);
							if (cursorX + metrics.width > x + w && cursorX > x + 4) {
								cursorX = x + 4;
								cursorY += lineHeight;
							}
							if (cursorY > y + h) break;
							ctx.fillText(word, cursorX, cursorY);
							cursorX += metrics.width;
						}
					}

					cursorY += lineHeight * 0.4;
				}

				ctx.restore();
			}

			let dataUrl: string;
			try {
				dataUrl = canvas.toDataURL('image/png');
			} catch (e) {
				throw new Error(
					`Canvas export failed: ${e instanceof Error ? e.message : String(e)}`
				);
			}
			images.push(dataUrl);
		} catch (slideErr) {
			console.error('pptxToImages slide failed:', slidePath, slideErr);
			throw slideErr;
		}
	}

	return { images, width: slideW, height: slideH };
}
