// Service worker mínimo do FinanceApp.
// Existe para o Android tratar o site como app instalável (ícone + tela cheia) e para mostrar
// um aviso amigável sem internet. NÃO guarda páginas em cache: os dados são por usuário e mudam
// a todo momento, então tudo continua vindo do servidor.
const PAGINA_OFFLINE = `<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinanceApp — sem conexão</title>
<style>
  body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
         background: #0f172a; color: #f1f5f9; font-family: system-ui, sans-serif; text-align: center; padding: 24px; }
  h1 { font-size: 1.3rem; margin: 16px 0 8px; } p { color: #94a3b8; margin: 0 0 24px; }
  button { background: #3b82f6; color: #fff; border: 0; border-radius: 8px; padding: 12px 24px; font-size: 1rem; }
</style></head>
<body><div>
  <div style="font-size:3rem">📶</div>
  <h1>Sem conexão com a internet</h1>
  <p>O FinanceApp precisa de internet para mostrar seus dados.</p>
  <button onclick="location.reload()">Tentar de novo</button>
</div></body></html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
    // Só intercepta a abertura de páginas (GET); formulários, CSS, JS e imagens seguem direto.
    if (e.request.mode !== 'navigate' || e.request.method !== 'GET') return;
    e.respondWith(
        fetch(e.request).catch(() =>
            new Response(PAGINA_OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } }))
    );
});
