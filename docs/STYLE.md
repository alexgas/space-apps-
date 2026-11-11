# Guía de estilo (extraída de https://www.spaceappsvalencia.es/css/styles.css, 10/11/2026)

Tema oscuro espacial. Fuentes Google: Inter (texto), Orbitron (titulares, botones, badges), Outfit (subtítulos, nav).
Import original: `https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Orbitron:wght@500;700;800;900&family=Outfit:wght@400;500;600;700;800&display=swap`
La app debe funcionar sin internet: enlazar Google Fonts pero con fallbacks de sistema (`system-ui, -apple-system, sans-serif`).

## Variables :root (literales)
```css
--accent-orange: #ff6b00;
--accent-orange-glow: rgba(255,107,0,.4);
--bg-card: rgba(13,22,45,.65);
--bg-card-hover: rgba(20,34,66,.85);
--bg-dark: #040714;
--bg-glass: rgba(15,23,42,.7);
--border-color: rgba(255,255,255,.1);
--border-glow: rgba(0,240,255,.3);
--card-shadow: 0 10px 30px -10px rgba(0,0,0,.5);
--font-body: 'Inter', sans-serif;
--font-heading: 'Orbitron', sans-serif;
--font-subheading: 'Outfit', sans-serif;
--glow-cyan: 0 0 20px rgba(0,240,255,.35);
--glow-orange: 0 0 20px rgba(255,107,0,.35);
--glow-purple: 0 0 20px rgba(157,78,221,.35);
--nasa-red: #e11d48;
--primary-cyan: #00f0ff;
--primary-cyan-glow: rgba(0,240,255,.4);
--secondary-purple: #9d4edd;
--success-green: #10b981;
--text-main: #f8fafc;
--text-muted: rgb(175 175 175 / 75%);
--transition-fast: all .25s cubic-bezier(.4,0,.2,1);
```
body: background #040714, color #f8fafc, Inter 16px.

## Componentes clave (CSS original resumido)
- h1: Orbitron 900. h2/section-title: Orbitron 800, uppercase, letter-spacing 1px, texto con degradado `linear-gradient(135deg,#fff 30%,#00f0ff 100%)` (background-clip:text). h3: Outfit 700.
- `.section-tag`: pill inline-flex, padding 6px 16px, radius 50px, bg rgba(0,240,255,.08), border 1px var(--border-glow), color cyan, Orbitron .82rem, letter-spacing 2px, uppercase.
- `.glass-card`: bg var(--bg-card), backdrop-filter blur(16px), border 1px var(--border-color), radius 16px, shadow var(--card-shadow); `::before` línea superior 1px `linear-gradient(90deg,transparent,rgba(255,255,255,.2),transparent)`; hover: bg-card-hover, border-color border-glow, translateY(-5px), glow cyan.
- `.navbar-space`: bg rgba(4,7,20,.75), blur(20px), border-bottom 1px rgba(255,255,255,.08).
- `.nav-link-space`: Outfit 500 .95rem, color text-muted; hover/active color cyan con subrayado 2px cyan con glow (70% ancho).
- `.brand-badge`: degradado 135deg nasa-red→accent-orange, blanco, Orbitron .7rem 700, padding 3px 8px, radius 4px, letter-spacing 1px.
- `.btn-space-primary`: degradado 135deg #00c6ff→#0072ff, blanco, Orbitron .9rem 700, padding 12px 28px, radius 50px, sin borde, uppercase, letter-spacing 1px; hover invierte degradado, glow rgba(0,240,255,.8) 30px, translateY(-2px).
- `.btn-space-outline`: transparente, borde 1px cyan, mismo tipo; hover bg rgba(0,240,255,.15), color cyan.
- `.btn-space-accent`: degradado 135deg #ff6b00→#ff0055.
- `.time-tag`: bg rgba(0,240,255,.15), color cyan, Orbitron 700 .85rem, padding 4px 12px, radius 20px.
- `.hero-telemetry-badge`: pill bg rgba(0,240,255,.08), borde border-glow, Orbitron .85rem cyan (texto tipo "MISIÓN VALENCIA 2026 • ESTADO: OPERATIVO").
- `.agenda-tab-btn` (tabs): bg rgba(15,23,42,.7), borde border-color, text-muted, Orbitron .9rem, pill; active: degradado cyan→#0072ff, blanco, glow.
- `.form-control-space`: bg rgba(15,23,42,.8), borde border-color, blanco, radius 10px, padding .8rem 1rem; focus borde cyan + glow.
- Chips de dificultad: usar cyan/purple/orange con fondos al 12–15%.
