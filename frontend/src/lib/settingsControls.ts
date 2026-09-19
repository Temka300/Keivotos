export function compactSegmentClass(active: boolean) {
    return `px-3 py-1.5 text-xs font-medium transition-colors ${
      active
        ? 'bg-purple-600/25 text-purple-100'
        : 'bg-[#0d0d13] text-gray-500 hover:bg-[#171720] hover:text-gray-200'
    }`;
  }

export function iconPath(icon: string) {
    if (icon === 'folder') {
      return 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z';
    }
    if (icon === 'palette') {
      return 'M12 3a9 9 0 00-3 17.49c.6.2 1-.28.83-.87-.22-.76.27-1.54 1.06-1.54h1.33c4.18 0 7.56-3.05 7.56-6.82C19.78 6.7 16.3 3 12 3zm-4 8h.01M11 7h.01M15 8h.01M16 12h.01';
    }
    if (icon === 'database') {
      return 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6m-16 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6';
    }
    if (icon === 'shield') {
      return 'M12 3l7 3v5c0 4.6-2.8 8.2-7 10-4.2-1.8-7-5.4-7-10V6l7-3zm-3 9l2 2 4-4';
    }
    if (icon === 'image') {
      return 'M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm2 10l4-4 3 3 4-5 3 4M9 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3z';
    }
    return 'M4 5h16v14H4V5zm0 4h16M8 5v4';
  }

export function formatByteCount(value: number) {
    if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
    if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(2)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${value.toLocaleString()} B`;
  }

