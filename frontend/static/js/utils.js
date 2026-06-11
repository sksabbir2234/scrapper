function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function stripHtml(html) {
    if (!html) return '';
    const div = document.createElement('div');
    div.innerHTML = html;
    return div.textContent || div.innerText || '';
}

function truncate(text, len) {
    if (!text) return '';
    text = stripHtml(text);
    return text.length > len ? text.substring(0, len) + '...' : text;
}
