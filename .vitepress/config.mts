import { posix } from 'node:path'
import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

const REPO = 'https://github.com/tyevco/prettycoolboards'

// The site is built from the repository root, so the relative links that work on GitHub work here too.
// Links to anything that is not a page (Python, KiCad, STEP, folders...) go to the file on GitHub.
function repoLinks(md: any) {
  const next = md.renderer.rules.link_open ??
    ((tokens: any, idx: number, options: any, _env: any, self: any) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens: any, idx: number, options: any, env: any, self: any) => {
    const token = tokens[idx]
    const href: string | null = token.attrGet('href')
    if (href && !/^([a-z][a-z0-9+.-]*:|#|\/)/i.test(href)) {
      const [path, hash] = href.split('#')
      const isPage = path === '' || /\.(md|html)$/i.test(path)
      if (isPage && /(^|\/)README\.md$/i.test(path)) {
        // a README is its folder's index page on the site (see rewrites), so link to the folder
        token.attrSet('href', path.replace(/README\.md$/i, '') + (hash ? '#' + hash : ''))
      } else if (!isPage) {
        const target = posix.normalize(posix.join(posix.dirname(env.relativePath ?? ''), path))
        const kind = path.endsWith('/') ? 'tree' : 'blob'
        token.attrSet('href', `${REPO}/${kind}/main/${target.replace(/\/$/, '')}${hash ? '#' + hash : ''}`)
      }
    }
    return next(tokens, idx, options, env, self)
  }
}

export default withMermaid(defineConfig({
  title: 'prettycoolboards',
  description: 'Open hardware boards designed as code: KiCad generated from Python, mechanics in build123d.',
  base: '/prettycoolboards/',
  lang: 'en-US',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: [/\/hardware\/sim\/results\//],
  // README.md files are the index pages of their folders
  // (at any depth: caliper/hardware/mechanical/README.md is served at /caliper/hardware/mechanical/)
  rewrites: { 'README.md': 'index.md', ':path(.*)/README.md': ':path/index.md' },
  srcExclude: ['**/hardware/kicad/**', '**/hardware/fab/**', '**/node_modules/**', '**/managed_components/**',
    '**/firmware/build/**', '**/.pytest_cache/**', '.github/**', 'CLAUDE*.md'],
  markdown: { config: (md) => { md.use(repoLinks) } },
  vite: { build: { chunkSizeWarningLimit: 3000 } },
  themeConfig: {
    nav: [
      { text: 'Caliper', link: '/caliper/' },
      { text: 'Toolchain', link: '/tools/' },
      { text: 'GitHub', link: REPO },
    ],
    sidebar: {
      '/caliper/': [
        {
          text: 'PrettyCool Caliper',
          items: [
            { text: 'Overview', link: '/caliper/' },
            // a static page from public/: an absolute URL so the router doesn't treat it as a doc page
            { text: '3D gallery', link: 'https://tyevco.github.io/prettycoolboards/caliper/gallery/' },
            { text: 'Architecture', link: '/caliper/docs/architecture' },
            { text: 'SPEC (architecture of record)', link: '/caliper/hardware/design/SPEC' },
          ],
        },
        {
          text: 'Hardware',
          items: [
            { text: 'Schematics & boards', link: '/caliper/docs/electronics' },
            { text: 'Mechanical design', link: '/caliper/docs/mechanical' },
            { text: 'Simulation', link: '/caliper/docs/simulation' },
            { text: 'Assembly and ordering', link: '/caliper/docs/assembly' },
            { text: 'Order checklist', link: '/caliper/docs/ordering' },
            { text: 'Bring-up', link: '/caliper/docs/bringup' },
          ],
        },
        {
          text: 'Software',
          items: [
            { text: 'Firmware', link: '/caliper/docs/firmware' },
            { text: 'Companion app', link: '/caliper/docs/app' },
          ],
        },
        {
          text: 'Future ideas',
          items: [
            { text: 'Oh, neat: maybe later', link: '/caliper/docs/ideas/' },
            { text: 'Electronic slide lock', link: '/caliper/docs/ideas/slide-lock' },
          ],
        },
      ],
    },
    outline: { level: [2, 3] },
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: REPO }],
    editLink: { pattern: `${REPO}/edit/main/:path`, text: 'Edit this page on GitHub' },
    footer: { message: 'Hardware design files, docs and generators for prettycoolboards.' },
  },
  mermaid: {},
}))
