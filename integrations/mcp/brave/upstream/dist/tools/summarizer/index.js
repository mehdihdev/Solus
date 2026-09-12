import { summarizerQueryParams } from './params.js';
import API from '../../BraveAPI/index.js';
export const name = 'brave_summarizer';
export const annotations = {
    title: 'Brave Summarizer',
    openWorldHint: true,
};
export const description = `
    Retrieves AI-generated summaries of web search results using Brave's Summarizer API. This tool processes search results to create concise, coherent summaries of information gathered from multiple sources.

    When to use:

    - When you need a concise overview of complex topics from multiple sources
    - For quick fact-checking or getting key points without reading full articles
    - When providing users with summarized information that synthesizes various perspectives
    - For research tasks requiring distilled information from web searches

    Returns a text summary that consolidates information from the search results. Optional features include inline references to source URLs and additional entity information.

    Requirements: Must first perform a web search using brave_web_search with summary=true parameter. Requires a Pro AI subscription to access the summarizer functionality.
`.trim();
export const execute = async (params) => {
    const response = { content: [], isError: false };
    try {
        const { summary } = await pollForSummary(params);
        if (!summary || summary.length === 0) {
            response.isError = true;
            response.content.push({
                type: 'text',
                text: 'Unable to retrieve a Summarizer summary.',
            });
        }
        else {
            const summaryText = summary
                .map((summary_part) => {
                if (summary_part.type === 'token') {
                    return summary_part.data;
                }
                else if (summary_part.type === 'inline_reference') {
                    return ` (${summary_part.data?.url})`;
                }
                else {
                    return '';
                }
            })
                .join('');
            response.content.push({
                type: 'text',
                text: summaryText,
            });
        }
    }
    catch (error) {
        response.isError = true;
        response.content.push({
            type: 'text',
            text: 'Unable to retrieve a Summarizer summary.',
        });
    }
    return response;
};
export const register = (mcpServer) => {
    mcpServer.registerTool(name, {
        title: name,
        description: description,
        inputSchema: summarizerQueryParams,
        annotations: annotations,
    }, execute);
};
const pollForSummary = async (params, pollInterval = 50, attempts = 20) => {
    let result = null;
    while (!result && attempts > 0) {
        try {
            const response = await API.issueRequest('summarizer', params);
            if (response.status === 'complete') {
                result = response;
            }
        }
        catch (error) {
            await new Promise((resolve) => setTimeout(resolve, pollInterval));
        }
        attempts--;
    }
    if (!result) {
        throw new Error('Summarizer summary could not be retrieved after multiple attempts.');
    }
    return result;
};
export default {
    name,
    description,
    annotations,
    inputSchema: summarizerQueryParams.shape,
    execute,
    register,
};
