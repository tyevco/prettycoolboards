// The default theme, plus two readability helpers for every page (see custom.css):
//  * doc images open full size in a native <dialog> (click or Enter; Esc, a click or Close shuts it),
//  * on narrow screens each Mermaid diagram keeps a readable size and scrolls inside its own box.
// The Mermaid component itself is registered by vitepress-plugin-mermaid (withMermaid in config.mts), not here.
import DefaultTheme from 'vitepress/theme'
import { inBrowser, type Theme } from 'vitepress'
import './custom.css'

// Mermaid draws at 16 px. On a phone, a diagram is shown at least this wide (or at its own width if smaller) and at
// no less than this fraction of its own width, so its text stays at about 10 px or more. custom.css applies it.
const MERMAID_MIN_PX = 560
const MERMAID_MIN_SCALE = 0.6

let dialog: HTMLDialogElement | null = null

function zoomDialog(): HTMLDialogElement {
  if (dialog) return dialog
  const d = document.createElement('dialog')
  d.className = 'img-zoom'
  d.setAttribute('aria-label', 'Image at full size')
  d.innerHTML = '<img alt=""><form method="dialog"><button>Close</button></form>'
  // a click anywhere closes it (Esc does too, natively); scrolling the image does not count as a click
  d.addEventListener('click', () => d.close())
  document.body.appendChild(d)
  return (dialog = d)
}

function openZoom(src: HTMLImageElement) {
  const d = zoomDialog()
  const img = d.querySelector('img')!
  img.src = src.currentSrc || src.src
  img.alt = src.alt
  d.showModal()
  d.scrollTo(0, 0)
}

// Doc images that are not links: make each one open the dialog, by mouse or keyboard.
function bindImages() {
  document.querySelectorAll<HTMLImageElement>('.vp-doc img:not([data-zoom])').forEach((img) => {
    img.dataset.zoom = img.closest('a, .mermaid') ? 'off' : 'on'
    if (img.dataset.zoom === 'off') return
    img.tabIndex = 0
    img.addEventListener('click', () => openZoom(img))
    img.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        openZoom(img)
      }
    })
  })
}

// Mermaid re-renders a diagram's SVG (on load and on a theme switch), so each new SVG gets its own width variable.
function sizeMermaid() {
  document.querySelectorAll<SVGSVGElement>('.vp-doc .mermaid svg:not([data-mw])').forEach((svg) => {
    const own =
      parseFloat(svg.style.maxWidth) || svg.viewBox?.baseVal?.width || parseFloat(svg.getAttribute('width') ?? '')
    svg.dataset.mw = own ? String(Math.round(own)) : 'none'
    if (!own) return
    const min = Math.min(own, Math.max(MERMAID_MIN_PX, own * MERMAID_MIN_SCALE))
    svg.style.setProperty('--mermaid-min-width', `${Math.round(min)}px`)
  })
}

let queued = false
function enhance() {
  if (queued) return
  queued = true
  requestAnimationFrame(() => {
    queued = false
    bindImages()
    sizeMermaid()
  })
}

export default {
  extends: DefaultTheme,
  enhanceApp({ router }) {
    if (!inBrowser) return
    // the page content and the Mermaid SVGs arrive after a route change, and Mermaid renders asynchronously
    new MutationObserver(enhance).observe(document.body, { childList: true, subtree: true })
    const next = router.onAfterRouteChange
    router.onAfterRouteChange = async (to) => {
      await next?.(to)
      dialog?.close()
      enhance()
    }
    enhance()
  },
} satisfies Theme
