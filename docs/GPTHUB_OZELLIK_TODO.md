# GPTHub özellik şablonu — görev listesi

Bu liste şablondaki maddeleri takip içindir. Durumlar: **Tamamlandı** | **Kısmen** | **Bekliyor**.

## Zorunlu (обязательная)

| # | Özellik | Durum | Not |
|---|---------|-------|-----|
| 1 | Metin sohbeti | Tamamlandı | Open WebUI çekirdeği |
| 2 | Sesli sohbet | Tamamlandı | Çağrı / ses modu |
| 3 | Sohbette görsel üretimi | Tamamlandı | MWS görsel pipeline |
| 4 | Ses dosyası + otomatik ASR | Tamamlandı | Whisper vb. |
| 5 | Görseller (VLM) | Tamamlandı | Vision modelleri |
| 6 | Dosyalar ve içeriğe göre yanıt (RAG) | Tamamlandı | Bilgi / dosya pipeline |
| 7 | İnternette arama | Tamamlandı | Web araması özelliği |
| 8 | Mesajdaki bağlantıdan web parse | Tamamlandı | URL sayfa bağlamı |
| 9 | Uzun vadeli hafıza | Tamamlandı | Kayıtlı anılar + sohbette enjeksiyon (`USER_MEMORY_TOP_K`, varsayılan bellek açık) |
| 10 | Göreve göre otomatik model | Tamamlandı | MWS Auto |
| 11 | Elle model seçimi | Tamamlandı | Model seçici (tüm modeller listelenir) |
| 12 | Markdown ve biçimli kod | Tamamlandı | Sohbet render |

## Ek (дополнительная)

| # | Özellik | Durum | Not |
|---|---------|-------|-----|
| 13 | Deep Research / research modu | Kısmen | Web + derin düşünme bayrakları; ürün politikasına göre genişletilebilir |
| 14 | Sunum üretimi | Bekliyor / Kısmen | Ayrı araç veya export ile bağlanabilir |
| 15 | Diğer ek işlevler | — | Vaka ihtiyacına göre |

---

**Son güncelleme:** Uzun vadeli hafıza iyileştirmesi ve model listesinde tüm modellerin gösterimi uygulandı.

**Ortam:** `USER_MEMORY_TOP_K` (varsayılan 8, üst sınır 32) — anılardan kaç girişin bağlama ekleneceği.
