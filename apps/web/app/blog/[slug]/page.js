import Link from "next/link";
import { notFound } from "next/navigation";
import SiteFooter from "../../../components/site-footer";
import SiteHeader from "../../../components/site-header";
import {
  formatPostDate,
  getAllPostSlugs,
  getPostBySlug,
} from "../../../lib/posts";

export async function generateStaticParams() {
  const slugs = await getAllPostSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }) {
  const { slug } = await params;
  const post = await getPostBySlug(slug);

  if (!post) {
    return {
      title: "Post Not Found | Solus",
    };
  }

  return {
    title: `${post.title} | Solus`,
    description: post.excerpt,
  };
}

export default async function BlogPostPage({ params }) {
  const { slug } = await params;
  const post = await getPostBySlug(slug);

  if (!post) {
    notFound();
  }

  return (
    <>
      <SiteHeader />

      <main className="blog-post-page">
        <section className="blog-post-header">
          <div className="container article-container">
            <Link href="/blog" className="blog-post-back">
              ← Back to blog
            </Link>
            <div className="blog-post-meta">
              {post.category ? (
                <Link href={`/blog?category=${post.categorySlug}`} className="blog-category-tag">
                  {post.category}
                </Link>
              ) : null}
              <p className="blog-post-date">{formatPostDate(post.date) ?? "Draft"}</p>
            </div>
            <h1>{post.title}</h1>
            <p className="blog-post-excerpt">{post.excerpt}</p>
          </div>
        </section>

        <section className="blog-post-body">
          <div
            className="container article-container blog-post-content"
            dangerouslySetInnerHTML={{ __html: post.contentHtml }}
          />
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
