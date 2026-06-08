import Link from "next/link";
import SiteFooter from "../../components/site-footer";
import SiteHeader from "../../components/site-header";
import {
  formatPostDate,
  getAllCategories,
  getAllPosts,
  getPostsByCategory,
} from "../../lib/posts";

export const metadata = {
  title: "Blog | Solus Forge",
  description:
    "Updates, product notes, and engineering writing from the Solus Forge team.",
};

export default async function BlogPage({ searchParams }) {
  const posts = await getAllPosts();
  const categories = await getAllCategories();
  const resolvedSearchParams = await searchParams;
  const activeCategory = resolvedSearchParams?.category ?? "";
  const filteredPosts = getPostsByCategory(posts, activeCategory);
  const activeCategoryLabel =
    categories.find((category) => category.slug === activeCategory)?.label ?? null;

  return (
    <>
      <SiteHeader />

      <main className="blog-page">
        <section className="blog-hero">
          <div className="container">
            <p className="section-label">Blog</p>
            <div className="blog-hero-copy">
              <h1>Perspectives on the future of robotics</h1>
              <p>
                Product notes, engineering ideas, and operating lessons from the team
                building Solus Forge.
              </p>
            </div>
          </div>
        </section>

        <section className="blog-listing">
          <div className="container">
            {categories.length > 0 ? (
              <div className="blog-filters" aria-label="Blog categories">
                <Link
                  href="/blog"
                  className={`blog-filter${!activeCategory ? " active" : ""}`}
                >
                  All posts
                </Link>
                {categories.map((category) => (
                  <Link
                    href={`/blog?category=${category.slug}`}
                    className={`blog-filter${
                      activeCategory === category.slug ? " active" : ""
                    }`}
                    key={category.slug}
                  >
                    {category.label}
                    <span>{category.count}</span>
                  </Link>
                ))}
              </div>
            ) : null}

            {filteredPosts.length > 0 ? (
              <div className="blog-grid">
                {filteredPosts.map((post) => (
                  <article
                    className={`blog-card${post.image ? " has-image" : ""}`}
                    key={post.slug}
                  >
                    <div className="blog-card-body">
                      <div className="blog-card-meta">
                        {post.category ? (
                          <Link
                            href={`/blog?category=${post.categorySlug}`}
                            className="blog-category-tag"
                          >
                            {post.category}
                          </Link>
                        ) : null}
                        <span>{formatPostDate(post.date) ?? "Draft"}</span>
                      </div>
                      <h2>
                        <Link href={`/blog/${post.slug}`}>{post.title}</Link>
                      </h2>
                      <p>{post.excerpt}</p>
                      <Link href={`/blog/${post.slug}`} className="blog-card-link">
                        Read article →
                      </Link>
                    </div>
                    {post.image ? (
                      <Link href={`/blog/${post.slug}`} className="blog-card-image">
                        <img src={post.image} alt={post.imageAlt ?? post.title} />
                      </Link>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <div className="blog-empty">
                <h2>
                  {activeCategoryLabel
                    ? `No posts in ${activeCategoryLabel} yet.`
                    : "No posts yet."}
                </h2>
                <p>
                  Fresh writing from the Solus team will appear here soon.
                </p>
              </div>
            )}
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
