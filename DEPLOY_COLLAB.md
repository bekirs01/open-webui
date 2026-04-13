# Deploying the collab server

`server/collab.js` is a plain Node.js script with one dependency (`ws`).
It can be deployed to any platform that runs Node.js:

- **Railway / Render / Fly.io** — connect repo, set start command to `node server/collab.js`
- **VPS** — clone repo, `npm install`, run with `pm2 start server/collab.js`
- **Local network only** — `npm run collab` is enough; share your local IP with friends on the same Wi-Fi

After deploying, set in your SvelteKit environment:

`PUBLIC_COLLAB_WS_URL=wss://your-deployed-url.com`
