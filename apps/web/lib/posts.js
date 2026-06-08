import { promises as fs } from "fs";
import path from "path";
import matter from "gray-matter";
import { remark } from "remark";
import html from "remark-html";

const postsDirectory = path.join(process.cwd(), "posts");

function normalizeCategory(value) {
  if (typeof value !== "string") {
    return null;
  }

  const category = value.trim();
  return category ? category : null;
}

function normalizeString(value) {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  return normalized ? normalized : null;
}

function categoryToSlug(category) {
  return category
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function slugToTitle(slug) {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeDate(value) {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10);
  }

  if (typeof value === "string") {
    return value.slice(0, 10);
  }

  return null;
}

function stripMarkdown(markdown) {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^>\s?/gm, "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_~]/g, "")
    .replace(/\n+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function createExcerpt(content, explicitExcerpt) {
  if (typeof explicitExcerpt === "string" && explicitExcerpt.trim()) {
    return explicitExcerpt.trim();
  }

  const plainText = stripMarkdown(content);

  if (plainText.length <= 180) {
    return plainText;
  }

  return `${plainText.slice(0, 177).trim()}...`;
}

async function readPostFile(fileName, includeHtml = false) {
  const slug = fileName.replace(/\.md$/, "");
  const filePath = path.join(postsDirectory, fileName);
  const fileContents = await fs.readFile(filePath, "utf8");
  const { data, content } = matter(fileContents);
  const date = normalizeDate(data.date);
  const category = normalizeCategory(data.category);
  const image = normalizeString(data.image);
  const imageAlt = normalizeString(data.imageAlt);

  const post = {
    slug,
    title: typeof data.title === "string" && data.title.trim()
      ? data.title.trim()
      : slugToTitle(slug),
    excerpt: createExcerpt(content, data.excerpt),
    category,
    categorySlug: category ? categoryToSlug(category) : null,
    image,
    imageAlt: imageAlt ?? (image ? `${slugToTitle(slug)} cover image` : null),
    date,
    sortTime: date ? Date.parse(`${date}T12:00:00Z`) : 0,
  };

  if (!includeHtml) {
    return post;
  }

  const processedContent = await remark().use(html).process(content);

  return {
    ...post,
    contentHtml: processedContent.toString(),
  };
}

export async function getAllPosts() {
  let fileNames = [];

  try {
    fileNames = await fs.readdir(postsDirectory);
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return [];
    }

    throw error;
  }

  const posts = await Promise.all(
    fileNames
      .filter((fileName) => fileName.endsWith(".md"))
      .map((fileName) => readPostFile(fileName)),
  );

  return posts.sort((left, right) => {
    if (right.sortTime !== left.sortTime) {
      return right.sortTime - left.sortTime;
    }

    return left.title.localeCompare(right.title);
  });
}

export async function getAllPostSlugs() {
  const posts = await getAllPosts();
  return posts.map((post) => post.slug);
}

export async function getAllCategories() {
  const posts = await getAllPosts();
  const categories = new Map();

  posts.forEach((post) => {
    if (!post.category || !post.categorySlug) {
      return;
    }

    const current = categories.get(post.categorySlug);

    if (current) {
      current.count += 1;
      return;
    }

    categories.set(post.categorySlug, {
      label: post.category,
      slug: post.categorySlug,
      count: 1,
    });
  });

  return [...categories.values()].sort((left, right) =>
    left.label.localeCompare(right.label),
  );
}

export async function getPostBySlug(slug) {
  try {
    return await readPostFile(`${slug}.md`, true);
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return null;
    }

    throw error;
  }
}

export function formatPostDate(date) {
  if (!date) {
    return null;
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}

export function getPostsByCategory(posts, categorySlug) {
  if (!categorySlug) {
    return posts;
  }

  return posts.filter((post) => post.categorySlug === categorySlug);
}
