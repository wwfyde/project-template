import Layout from './(docs)/layout';
import { Link } from 'docs-mdx/src/components/Link';
import { siteConfig } from 'docs-mdx/src/site.config.mjs';

export default function NotFoundPage() {
  return (
    <Layout>
      <h1 className="MdH1">页面不存在</h1>
      <p className="MdP">
        请返回 <Link href={siteConfig.entryPath}>文档首页</Link>。
      </p>
    </Layout>
  );
}
