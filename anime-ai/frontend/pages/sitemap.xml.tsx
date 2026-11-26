import type { GetServerSideProps } from 'next';

const PUBLIC_PATHS = ['/', '/about', '/contact', '/privacy', '/terms', '/login'];

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  const proto = (req.headers['x-forwarded-proto'] as string) || 'https';
  const host = req.headers.host || 'localhost:3000';
  const baseUrl =
    configured && /^https?:\/\//.test(configured)
      ? configured.replace(/\/$/, '')
      : `${proto}://${host}`;

  const urls = PUBLIC_PATHS.map(
    (path) => `  <url>\n    <loc>${baseUrl}${path}</loc>\n    <changefreq>weekly</changefreq>\n  </url>`
  ).join('\n');

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;

  res.setHeader('Content-Type', 'application/xml');
  res.write(xml);
  res.end();

  return { props: {} };
};

export default function SitemapXml() {
  return null;
}
