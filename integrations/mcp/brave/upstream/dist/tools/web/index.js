import params from './params.js';
import API from '../../BraveAPI/index.js';
import { stringify } from '../../utils.js';
export const name = 'brave_web_search';
export const annotations = {
    title: 'Brave Web Search',
    openWorldHint: true,
};
export const description = `
    Performs web searches using the Brave Search API and returns comprehensive search results with rich metadata.

    When to use:
        - General web searches for information, facts, or current topics
        - Location-based queries (restaurants, businesses, points of interest)
        - News searches for recent events or breaking stories
        - Finding videos, discussions, or FAQ content
        - Research requiring diverse result types (web pages, images, reviews, etc.)

    Returns a JSON list of web results with title, description, and URL.
    
    When the "results_filter" parameter is empty, JSON results may also contain FAQ, Discussions, News, and Video results.
`.trim();
export const execute = async (params) => {
    const response = { content: [], isError: false };
    const { web, faq, discussions, news, videos, summarizer } = await API.issueRequest('web', params);
    if (summarizer) {
        response.content.push({
            type: 'text',
            text: `Summarizer key: ${summarizer.key}`,
        });
    }
    if (!web || !Array.isArray(web.results) || web.results.length < 1) {
        response.isError = true;
        response.content.push({
            type: 'text',
            text: 'No web results found',
        });
        return response;
    }
    // TODO (Sampson): The following is unnecessarily repetitive.
    if (web && web.results?.length > 0) {
        for (const entry of formatWebResults(web)) {
            response.content.push({
                type: 'text',
                text: stringify(entry),
            });
        }
    }
    if (faq && faq.results?.length > 0) {
        for (const entry of formatFAQResults(faq)) {
            response.content.push({
                type: 'text',
                text: stringify(entry),
            });
        }
    }
    if (discussions && discussions.results?.length > 0) {
        for (const entry of formatDiscussionsResults(discussions)) {
            response.content.push({
                type: 'text',
                text: stringify(entry),
            });
        }
    }
    if (news && news.results?.length > 0) {
        for (const entry of formatNewsResults(news)) {
            response.content.push({
                type: 'text',
                text: stringify(entry),
            });
        }
    }
    if (videos && videos.results?.length > 0) {
        for (const entry of formatVideoResults(videos)) {
            response.content.push({
                type: 'text',
                text: stringify(entry),
            });
        }
    }
    return response;
};
export const formatWebResults = (web) => {
    return (web.results || []).map(({ url, title, description, extra_snippets }) => ({
        url,
        title,
        description,
        extra_snippets,
    }));
};
export const register = (mcpServer) => {
    mcpServer.registerTool(name, {
        title: name,
        description: description,
        inputSchema: params,
        annotations: annotations,
    }, execute);
};
const formatFAQResults = (faq) => {
    return (faq.results || []).map(({ question, answer, title, url }) => ({
        question,
        answer,
        title,
        url,
    }));
};
const formatDiscussionsResults = (discussions) => {
    return (discussions.results || []).map(({ url, data }) => ({
        mutated_by_goggles: discussions.mutated_by_goggles,
        url,
        data,
    }));
};
const formatNewsResults = (news) => {
    return (news.results || []).map(({ source, breaking, is_live, age, url, title, description, extra_snippets }) => ({
        mutated_by_goggles: news.mutated_by_goggles,
        source,
        breaking,
        is_live,
        age,
        url,
        title,
        description,
        extra_snippets,
    }));
};
const formatVideoResults = (videos) => {
    return (videos.results || []).map(({ url, age, title, description, video, thumbnail }) => ({
        mutated_by_goggles: videos.mutated_by_goggles,
        url,
        title,
        description,
        age,
        thumbnail_url: thumbnail?.src,
        duration: video.duration,
        view_count: video.views,
        creator: video.creator,
        publisher: video.publisher,
        tags: video.tags,
    }));
};
export default {
    name,
    description,
    annotations,
    inputSchema: params.shape,
    execute,
    register,
};
