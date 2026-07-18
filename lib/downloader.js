import { fetch } from 'sdk';

export async function processMediaLink(url) {
    // Note: Fetch responses are capped at 32MB in Serverless.
    // Call your 3rd-party downloader API here.
    const apiUrl = `https://api.example.com/download?url=${encodeURIComponent(url)}`;
    
    /* 
    const res = await fetch(apiUrl);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    return data.direct_url;
    */
    
    return `[Mock API Response] Download ready for: ${url}`;
}