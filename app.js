const state = {
  view: "summary",
  channelFilter: "all",
  categoryFilter: "all",
  dateFilter: "all",
  sortBy: "published_desc",
  keywordFilter: "",
  selectedVideoId: null,
  loadWarnings: [],
  apiAvailable: false,
  previewMode: false,
  channelDetailCache: new Map(),
};

const appData = {
  meta: {
    notion_source_url: "",
  },
  channels: [],
  videos: [],
  todayVideos: [],
  groupedHistory: [],
  digest: {
    summary: "",
    summary_points: [],
    action_chips: [],
    creator_takeaway: "",
    topic_clusters: [],
    title_suggestions: [],
    recommendations: [],
    video_highlights: [],
    telegram_preview: "",
    generated_at: null,
    video_count: 0,
    total_recent_video_count: 0,
    average_view_count: 0,
    average_engagement_rate: 0,
    average_like_count: 0,
    average_comment_count: 0,
    best_video_id: "",
    best_topic: "",
    focus_scope: "all_watchlist",
  },
};

const bundledData = window.__DASHBOARD_DATA__ || {};
const DEFAULT_NOTION_URL = "https://www.notion.so/1c61ff0d0be880d39d6dd9faf563ed5c?v=1c61ff0d0be880d3b12d000c5768d1c9&source=copy_link";
const READ_ONLY_MESSAGE = "읽기 전용 미리보기입니다. Notion 가져오기와 업데이트 실행은 앱 실행 모드에서 사용할 수 있습니다. `open_dashboard.pyw`로 열면 전체 기능을 쓸 수 있습니다.";

function uniqueValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function escapeHtml(value) {
  return `${value || ""}`
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function compactNumber(value) {
  const safe = Number(value || 0);
  if (safe >= 1000000) {
    return `${(safe / 1000000).toFixed(1)}M`;
  }
  if (safe >= 1000) {
    return `${(safe / 1000).toFixed(1)}K`;
  }
  return `${Math.round(safe)}`;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatDateTime(value) {
  if (!value) {
    return "N/A";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "N/A";
  }
  return date.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

function formatDate(value) {
  if (!value) {
    return "N/A";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("ko-KR", { dateStyle: "medium" });
}

function kstDateKey(value) {
  if (!value) {
    return "날짜 없음";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "날짜 없음";
  }
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function formatDuration(value) {
  const seconds = Number(value || 0);
  if (!seconds) {
    return "N/A";
  }
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}시간 ${minutes}분`;
  }
  return `${Math.max(minutes, 1)}분`;
}

function isWithinRecentWindow(value, lookbackHours = 24, referenceTime = null) {
  if (!value) {
    return false;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  const now = referenceTime || new Date();
  return (now.getTime() - date.getTime()) <= lookbackHours * 60 * 60 * 1000;
}

function transcriptStatusText(video) {
  const status = video.transcript_status || "unknown";
  const source = video.transcript_source && video.transcript_source !== "none" ? ` · ${video.transcript_source}` : "";
  const language = video.transcript_language ? ` · ${video.transcript_language}` : "";
  if (status === "pending") {
    return `자막 수집 대기${source}${language}`;
  }
  if (status === "available") {
    return `수동 자막 확보${source}${language}`;
  }
  if (status === "available_auto") {
    return `자동 자막 확보${source}${language}`;
  }
  if (status === "translated") {
    return `번역 자막 확보${source}${language}`;
  }
  if (status === "description_only") {
    return "자막 없음 · 설명 기반 분석";
  }
  if (status === "failed") {
    return "자막 수집 실패";
  }
  if (status === "skipped") {
    return "자막 수집 대기";
  }
  if (status === "not_configured") {
    return "자막 수집 설정 없음";
  }
  return "자막 상태 미확인";
}

function truncateText(value, maxLength = 110) {
  const text = `${value || ""}`.trim();
  if (!text) {
    return "";
  }
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trim()}…`;
}

function splitBulletText(value, limit = 5) {
  const text = `${value || ""}`.trim();
  if (!text) {
    return [];
  }

  const bulletSeed = text
    .replace(/\r/g, "")
    .replace(/\n+/g, "\n")
    .replace(/\s*•\s*/g, "\n• ")
    .replace(/\s*[-●▪]\s+/g, "\n• ")
    .trim();

  let items = bulletSeed
    .split(/\n+/)
    .map((item) => item.replace(/^[•\-\d.)\s]+/, "").trim())
    .filter(Boolean);

  if (items.length <= 1) {
    items = text
      .split(/(?<=[.!?])\s+(?=[가-힣A-Za-z0-9"'(])/)
      .map((item) => item.trim())
      .filter((item) => item.length > 14);
  }

  return uniqueValues(items).slice(0, limit);
}

function transcriptParagraphs(value) {
  return `${value || ""}`
    .replace(/\r/g, "")
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
}

function creatorIdeaPoints(video) {
  const direct = splitBulletText(video.recommendation, 5);
  if (direct.length >= 3) {
    return direct;
  }

  const fallback = [];
  if (video.why_it_works) {
    fallback.push(`훅/포장 포인트: ${truncateText(video.why_it_works, 110)}`);
  }
  (video.transcript_highlights || []).slice(0, 2).forEach((item) => {
    fallback.push(`콘텐츠 기획 포인트: ${item}`);
  });
  const topComment = (video.top_comments || [])
    .slice()
    .sort((left, right) => (right.like_count || 0) - (left.like_count || 0) || (right.reply_count || 0) - (left.reply_count || 0))[0];
  if (topComment?.text) {
    fallback.push(`반응 신호: 댓글에서는 '${truncateText(topComment.text, 76)}' 같은 지점이 눈에 띄었습니다.`);
  }
  if (video.title_pattern) {
    fallback.push(`제목/패키징: '${video.title_pattern}' 구조를 내 채널 주제에 맞는 사례형 제목으로 변형해볼 만합니다.`);
  }
  return uniqueValues(fallback).slice(0, 5);
}

function channelDescriptionParagraphs(text) {
  const raw = `${text || ""}`
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter((line) => line && !/^email\s*:|^contact\s*:/i.test(line));

  const normalized = raw.join(" ").replace(/\s{2,}/g, " ").trim();
  if (!normalized) {
    return [];
  }

  const sentenceSeed = normalized.replace(/([.!?])\s+/g, "$1|");
  const sentences = sentenceSeed.split("|").map((item) => item.trim()).filter(Boolean);
  if (!sentences.length) {
    return [normalized];
  }

  const paragraphs = [];
  for (let index = 0; index < sentences.length; index += 2) {
    paragraphs.push(sentences.slice(index, index + 2).join(" "));
  }
  return paragraphs.slice(0, 3);
}

function normalizeWatchlistPayload(payload) {
  const channels = Array.isArray(payload) ? payload : payload.channels || [];
  return channels.map((channel) => ({
    channel_key: channel.channel_key || channel.youtube_channel_id || channel.url || channel.name || "",
    youtube_channel_id: channel.youtube_channel_id || "",
    name: channel.name || "이름 없는 채널",
    url: channel.url || "",
    category: channel.category || "미분류",
    language: channel.language || "미지정",
    is_active: channel.is_active !== false,
    source: channel.source || "manual",
    last_synced_at: channel.last_synced_at || null,
    subscriber_count: Number(channel.subscriber_count || 0),
    channel_view_count: Number(channel.channel_view_count || 0),
    video_count: Number(channel.video_count || 0),
    description: channel.description || "",
    country: channel.country || "",
    published_at: channel.published_at || null,
    thumbnail_url: channel.thumbnail_url || "",
    notes: channel.notes || "",
    notion_row_id: channel.notion_row_id || "",
  }));
}

function normalizeComment(comment, index) {
  if (typeof comment === "string") {
    return {
      comment_id: `comment-${index + 1}`,
      author: "",
      text: comment,
      like_count: 0,
      reply_count: 0,
      published_at: null,
    };
  }
  return {
    comment_id: comment.comment_id || `comment-${index + 1}`,
    author: comment.author || "",
    text: comment.text || "",
    like_count: Number(comment.like_count || 0),
    reply_count: Number(comment.reply_count || 0),
    published_at: comment.published_at || null,
  };
}

function normalizeVideoPayload(payload) {
  const videos = Array.isArray(payload) ? payload : payload.videos || [];
  return videos.map((video) => ({
    video_id: video.video_id || "",
    channel_id: video.channel_id || "",
    channel_key: video.channel_key || video.channel_id || "",
    channel_name: video.channel_name || "",
    title: video.title || "제목 없음",
    description: video.description || "",
    published_at: video.published_at || null,
    analysis_date: video.analysis_date || null,
    duration_seconds: Number(video.duration_seconds || 0),
    view_count: Number(video.view_count || 0),
    like_count: Number(video.like_count || 0),
    comment_count: Number(video.comment_count || 0),
    engagement_rate: video.engagement_rate !== undefined ? Number(video.engagement_rate) : 0,
    thumbnail_url: video.thumbnail_url || "",
    video_url: video.video_url || (video.video_id ? `https://www.youtube.com/watch?v=${video.video_id}` : ""),
    format: video.format || "미분류",
    hook_type: video.hook_type || "미분류",
    title_pattern: video.title_pattern || "패턴 미분류",
    topic_tags: uniqueValues(video.topic_tags || []),
    keywords: uniqueValues(video.keywords || []),
    tools: uniqueValues(video.tools || []),
    one_line_summary: video.one_line_summary || "",
    why_it_works: video.why_it_works || "",
    recommendation: video.recommendation || "",
    flow: Array.isArray(video.flow) ? video.flow : [],
    claims: Array.isArray(video.claims) ? video.claims : [],
    transcript_highlights: Array.isArray(video.transcript_highlights) ? video.transcript_highlights : [],
    top_comments: Array.isArray(video.top_comments) ? video.top_comments.map(normalizeComment) : [],
    transcript_status: video.transcript_status || "unknown",
    transcript_source: video.transcript_source || "none",
    transcript_language: video.transcript_language || "",
    transcript_text: video.transcript_text || "",
    is_recent: isWithinRecentWindow(video.published_at),
  }));
}

function normalizeRecommendation(item) {
  if (typeof item === "string") {
    return {
      title: item,
      hook: "",
      angle: "",
      thumbnail_copy: "",
      reason: "",
      source_video_id: "",
      source: "",
    };
  }
  return {
    title: item.title || "",
    hook: item.hook || "",
    angle: item.angle || "",
    thumbnail_copy: item.thumbnail_copy || "",
    reason: item.reason || "",
    source_video_id: item.source_video_id || "",
    source: item.source || "",
  };
}

function normalizeDigestPayload(payload) {
  return {
    summary: payload.summary || "",
    summary_points: Array.isArray(payload.summary_points) ? payload.summary_points : [],
    action_chips: Array.isArray(payload.action_chips) ? payload.action_chips : [],
    creator_takeaway: payload.creator_takeaway || "",
    topic_clusters: Array.isArray(payload.topic_clusters) ? payload.topic_clusters : [],
    title_suggestions: Array.isArray(payload.title_suggestions) ? payload.title_suggestions : [],
    recommendations: Array.isArray(payload.recommendations) ? payload.recommendations.map(normalizeRecommendation) : [],
    video_highlights: Array.isArray(payload.video_highlights) ? payload.video_highlights : [],
    telegram_preview: payload.telegram_preview || "",
    generated_at: payload.generated_at || null,
    video_count: Number(payload.video_count || 0),
    total_recent_video_count: Number(payload.total_recent_video_count || 0),
    average_view_count: Number(payload.average_view_count || 0),
    average_engagement_rate: Number(payload.average_engagement_rate || 0),
    average_like_count: Number(payload.average_like_count || 0),
    average_comment_count: Number(payload.average_comment_count || 0),
    best_video_id: payload.best_video_id || "",
    best_topic: payload.best_topic || "",
    focus_scope: payload.focus_scope || "all_watchlist",
  };
}

function currentNotionSourceUrl() {
  return appData.meta.notion_source_url || DEFAULT_NOTION_URL;
}

function groupVideosByDate(videos) {
  const groups = new Map();
  const today = kstDateKey(new Date().toISOString());
  videos.forEach((video) => {
    // analysis_date = 파이프라인 수집일(KST) 기준으로 그룹핑
    // published_at은 UTC 기반이라 날짜 경계에서 일별 종합과 불일치 발생
    const dateKey = kstDateKey(video.analysis_date || video.published_at);
    if (!groups.has(dateKey)) {
      groups.set(dateKey, {
        date: dateKey,
        label: dateKey,
        is_today: dateKey === today,
        videos: [],
      });
    }
    groups.get(dateKey).videos.push(video);
  });
  return [...groups.values()]
    .sort((left, right) => right.date.localeCompare(left.date))
    .map((group) => ({ ...group, video_count: group.videos.length }));
}

async function loadJson(path, fallbackFactory, warningMessage) {
  const bundleKey = path.includes("watchlist")
    ? "watchlist"
    : path.includes("videos")
      ? "videos"
      : path.includes("digest")
        ? "digest"
        : null;

  if (bundleKey && bundledData[bundleKey]) {
    return bundledData[bundleKey];
  }

  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    state.loadWarnings.push(`${warningMessage}: ${error.message}`);
    return fallbackFactory();
  }
}

async function hasDashboardApi() {
  if (!["http:", "https:"].includes(window.location.protocol)) {
    return false;
  }
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    return Boolean(payload && payload.ok);
  } catch (error) {
    return false;
  }
}

function hydrateVideos(videos, referenceTime = null) {
  const channelMap = Object.fromEntries(appData.channels.map((channel) => [channel.channel_key, channel]));
  const byYoutubeId = Object.fromEntries(appData.channels.map((channel) => [channel.youtube_channel_id, channel]));
  return videos.map((video) => {
    const channel = channelMap[video.channel_key] || byYoutubeId[video.channel_id] || {};
    const combinedTags = uniqueValues([...(video.topic_tags || []), ...(video.tools || []), ...(video.keywords || [])]);
    return {
      ...video,
      channel_key: video.channel_key || channel.channel_key || video.channel_id,
      channel_name: video.channel_name || channel.name || "알 수 없는 채널",
      channel_category: channel.category || "미분류",
      channel,
      combined_tags: combinedTags,
      search_text: [
        video.title,
        video.channel_name,
        video.one_line_summary,
        video.description,
        combinedTags.join(" "),
        video.transcript_text,
      ].join(" ").toLowerCase(),
      is_recent: isWithinRecentWindow(video.published_at, 24, referenceTime),
    };
  });
}

async function loadBootstrap() {
  const isFilePreview = window.location.protocol === "file:";
  const apiReady = !isFilePreview && await hasDashboardApi();

  if (apiReady) {
    try {
      const response = await fetch("/api/bootstrap", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      state.apiAvailable = true;
      state.previewMode = false;
      appData.meta = payload.meta || { notion_source_url: DEFAULT_NOTION_URL };
      appData.channels = normalizeWatchlistPayload(payload.channels || []);
      appData.videos = hydrateVideos(normalizeVideoPayload(payload.videos || []));
      appData.todayVideos = hydrateVideos(normalizeVideoPayload(payload.todayVideos || []));
      appData.groupedHistory = groupVideosByDate(appData.videos);
      appData.digest = normalizeDigestPayload(payload.digest || {});
      return;
    } catch (error) {
      state.apiAvailable = false;
      if (!bundledData.watchlist && !bundledData.videos && !bundledData.digest) {
        state.loadWarnings.push(`API bootstrap 실패: ${error.message}`);
      }
    }
  }

  const [watchlist, videos, digest] = await Promise.all([
    loadJson("data/watchlist.json", () => ({ channels: [] }), "watchlist.json을 읽지 못했습니다"),
    loadJson("data/videos.json", () => ({ videos: [] }), "videos.json을 읽지 못했습니다"),
    loadJson("data/digest.json", () => ({}), "digest.json을 읽지 못했습니다"),
  ]);

  state.previewMode = true;
  appData.meta = bundledData.meta || { notion_source_url: DEFAULT_NOTION_URL };
  appData.channels = normalizeWatchlistPayload(watchlist);
  appData.digest = normalizeDigestPayload(digest);
  const digestRefTime = appData.digest.generated_at ? new Date(appData.digest.generated_at) : null;
  appData.videos = hydrateVideos(normalizeVideoPayload(videos), digestRefTime);
  appData.groupedHistory = groupVideosByDate(appData.videos);
  appData.todayVideos = appData.videos.filter((video) => video.is_recent).slice(0, 200);

  if (!state.loadWarnings.length) {
    state.loadWarnings = [READ_ONLY_MESSAGE];
  } else {
    state.loadWarnings.unshift(READ_ONLY_MESSAGE);
  }
}

function focusScopeLabel(value) {
  if (value === "ai_creator_priority") {
    return "AI 크리에이터 우선 브리프";
  }
  if (value === "all_watchlist") {
    return "전체 워치리스트 기준";
  }
  return value || "대시보드 기준";
}

function renderStatusBanner() {
  const banner = document.getElementById("data-status");
  if (!state.loadWarnings.length) {
    banner.hidden = true;
    banner.textContent = "";
    banner.classList.remove("is-readonly");
    return;
  }
  banner.hidden = false;
  banner.classList.toggle("is-readonly", state.previewMode);
  banner.innerHTML = state.loadWarnings.map((warning) => escapeHtml(warning)).join("<br>");
}

function renderTopMeta() {
  const activeChannels = appData.channels.filter((channel) => channel.is_active);
  document.getElementById("digest-date").textContent = formatDate(appData.digest.generated_at);
  document.getElementById("sync-status").textContent = appData.digest.generated_at
    ? `${formatDateTime(appData.digest.generated_at)} 기준 브리프`
    : "최근 24시간 기준";
  document.getElementById("active-channel-count").textContent = `${activeChannels.length}개`;
  document.getElementById("watchlist-status").textContent = `전체 ${appData.channels.length}개 채널`;
  document.getElementById("recent-video-count").textContent = `${appData.todayVideos.length}개`;
  document.getElementById("focus-scope-label").textContent = focusScopeLabel(appData.digest.focus_scope);
}

function actionButtonsState() {
  const importButton = document.getElementById("import-notion-button");
  const runButton = document.getElementById("run-pipeline-button");
  const actionWrap = document.querySelector(".watchlist-actions");
  const disabled = !state.apiAvailable;
  importButton.disabled = disabled;
  runButton.disabled = disabled;
  importButton.classList.toggle("is-disabled", disabled);
  runButton.classList.toggle("is-disabled", disabled);
  if (actionWrap) {
    actionWrap.hidden = disabled;
  }
  if (disabled) {
    importButton.title = "앱 실행 모드에서만 사용할 수 있습니다.";
    runButton.title = "앱 실행 모드에서만 사용할 수 있습니다.";
  } else {
    importButton.title = "";
    runButton.title = "";
  }
}

function summaryKpis() {
  const bestVideo = appData.videos.find((video) => video.video_id === appData.digest.best_video_id)
    || appData.todayVideos[0]
    || null;
  const bestTopic = (appData.digest.topic_clusters || []).find((topic) => topic.label === appData.digest.best_topic)
    || (appData.digest.topic_clusters || [])[0]
    || null;
  return [
    {
      label: "평균 조회수",
      value: compactNumber(appData.digest.average_view_count),
      caption: "최근 24시간 영상 평균",
    },
    {
      label: "평균 참여율",
      value: formatPercent(appData.digest.average_engagement_rate),
      caption: `평균 좋아요 ${compactNumber(appData.digest.average_like_count)} · 평균 댓글 ${compactNumber(appData.digest.average_comment_count)}`,
    },
    {
      label: "오늘 최고 실적 영상",
      value: bestVideo ? truncateText(bestVideo.title, 54) : "데이터 없음",
      caption: bestVideo ? `${bestVideo.channel_name} · 조회수 ${compactNumber(bestVideo.view_count)} · 참여율 ${formatPercent(bestVideo.engagement_rate)}` : "데이터 없음",
      thumbnail_url: bestVideo?.thumbnail_url || "",
      meta: bestVideo?.channel_name || "",
    },
    {
      label: "오늘 최고 실적 주제",
      value: bestTopic ? bestTopic.label : "데이터 없음",
      caption: bestTopic ? `${bestTopic.count}개 · 평균 조회수 ${compactNumber(bestTopic.avg_view_count)} · 평균 참여율 ${formatPercent(bestTopic.avg_engagement_rate)}` : "데이터 없음",
      thumbnail_url: bestTopic?.thumbnail_url || "",
      meta: bestTopic?.representative_title || "",
    },
  ];
}

function fallbackSummaryPoints() {
  const points = [];
  if (appData.digest.summary) {
    points.push(appData.digest.summary);
  }
  if (appData.digest.creator_takeaway) {
    points.push(appData.digest.creator_takeaway);
  }
  return points.slice(0, 2);
}

function renderSummaryView() {
  document.getElementById("summary-text").textContent = appData.digest.summary || "요약 데이터가 없습니다.";
  document.getElementById("creator-takeaway").textContent = appData.digest.creator_takeaway || "크리에이터 액션 데이터가 없습니다.";
  document.getElementById("summary-points-list").innerHTML = (appData.digest.summary_points.length ? appData.digest.summary_points : fallbackSummaryPoints())
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  document.getElementById("action-chip-list").innerHTML = (appData.digest.action_chips || [])
    .map((item) => `<span class="action-chip">${escapeHtml(item)}</span>`)
    .join("");

  const kpis = summaryKpis();
  document.getElementById("summary-kpis").innerHTML = kpis.map((item) => `
    <article class="summary-kpi ${item.thumbnail_url ? "has-media" : ""}">
      <span class="label">${escapeHtml(item.label)}</span>
      ${item.thumbnail_url ? `
        <div class="summary-kpi-media">
          <img src="${escapeHtml(item.thumbnail_url)}" alt="">
          <div>
            <strong>${escapeHtml(item.value)}</strong>
            ${item.meta ? `<p class="summary-kpi-meta">${escapeHtml(item.meta)}</p>` : ""}
          </div>
        </div>
      ` : `<strong>${escapeHtml(item.value)}</strong>`}
      <small>${escapeHtml(item.caption)}</small>
    </article>
  `).join("");

  const topicRows = (appData.digest.topic_clusters || []).map((item) => `
    <tr>
      <td>
        <div class="topic-cell">
          ${item.thumbnail_url ? `<img class="topic-thumb" src="${escapeHtml(item.thumbnail_url)}" alt="">` : `<span class="topic-dot">#</span>`}
          <div>
            <strong>${escapeHtml(item.label)}</strong>
            <p>${escapeHtml(item.representative_title || "")}</p>
          </div>
        </div>
      </td>
      <td>${escapeHtml(String(item.count || 0))}</td>
      <td>${escapeHtml(compactNumber(item.avg_view_count || 0))}</td>
      <td>${escapeHtml(formatPercent(item.avg_engagement_rate || 0))}</td>
      <td>${escapeHtml((item.source_titles || []).slice(0, 2).join(" / "))}</td>
    </tr>
  `).join("");

  document.getElementById("topic-summary-table").innerHTML = topicRows
    ? `
      <table class="mini-table">
        <thead>
          <tr>
            <th>주제</th>
            <th>영상 수</th>
            <th>평균 조회수</th>
            <th>평균 참여율</th>
            <th>대표 제목</th>
          </tr>
        </thead>
        <tbody>${topicRows}</tbody>
      </table>
    `
    : `<div class="empty-state">오늘 많이 겹친 주제가 아직 없습니다.</div>`;

  document.getElementById("title-suggestion-list").innerHTML = (appData.digest.title_suggestions || []).length
    ? (appData.digest.title_suggestions || []).map((title) => `<li>${escapeHtml(title)}</li>`).join("")
    : `<li>추천 제목이 아직 없습니다.</li>`;

  document.getElementById("top-video-list").innerHTML = (appData.digest.video_highlights || []).length
    ? appData.digest.video_highlights.map((item) => `
      <button class="top-video-card js-open-video" data-video-id="${escapeHtml(item.video_id)}" type="button">
        <img class="top-video-thumb" src="${escapeHtml(item.thumbnail_url)}" alt="">
        <div class="top-video-body">
          <span class="top-video-eyebrow">${escapeHtml(item.topic_cluster || "핵심 영상")}</span>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary || "")}</p>
          <div class="top-video-meta">
            <span class="pill">${escapeHtml(item.channel_name)}</span>
            <span class="pill">조회수 ${escapeHtml(compactNumber(item.view_count))}</span>
            <span class="pill">좋아요 ${escapeHtml(compactNumber(item.like_count))}</span>
            <span class="pill">댓글 ${escapeHtml(compactNumber(item.comment_count))}</span>
            <span class="pill">참여율 ${escapeHtml(formatPercent(item.engagement_rate))}</span>
          </div>
        </div>
      </button>
    `).join("")
    : `<div class="empty-state">최고 실적 영상 데이터가 없습니다.</div>`;

  document.getElementById("recommendation-list").innerHTML = (appData.digest.recommendations || []).length
    ? appData.digest.recommendations.map((item) => `
      <article class="recommendation-card">
        <div class="recommendation-header">
          <div>
            <span class="recommendation-label">추천 제목</span>
            <h3>${escapeHtml(item.title)}</h3>
          </div>
          ${item.thumbnail_copy ? `<span class="thumbnail-copy">${escapeHtml(item.thumbnail_copy)}</span>` : ""}
        </div>
        ${item.hook ? `<p><strong>왜 클릭되는가</strong> ${escapeHtml(item.hook)}</p>` : ""}
        ${item.angle ? `<p><strong>내 채널에서 복제할 포장 요소</strong> ${escapeHtml(item.angle)}</p>` : ""}
        ${item.reason ? `<p><strong>비어 있는 콘텐츠 영역</strong> ${escapeHtml(item.reason)}</p>` : ""}
        ${item.source ? `<p class="muted">기준 영상: ${escapeHtml(item.source)}</p>` : ""}
      </article>
    `).join("")
    : `<div class="empty-state">추천 액션이 아직 없습니다.</div>`;
}

function populateFilters() {
  const channelOptions = [`<option value="all">전체 채널</option>`]
    .concat(appData.channels.map((channel) => `<option value="${escapeHtml(channel.channel_key)}">${escapeHtml(channel.name)}</option>`));
  document.getElementById("channel-filter").innerHTML = channelOptions.join("");

  const categories = uniqueValues(appData.channels.map((channel) => channel.category));
  document.getElementById("category-filter").innerHTML = [`<option value="all">전체 카테고리</option>`]
    .concat(categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`))
    .join("");

  const dates = appData.groupedHistory.map((group) => group.date);
  document.getElementById("date-filter").innerHTML = [`<option value="all">전체 날짜</option>`]
    .concat(dates.map((date) => `<option value="${escapeHtml(date)}">${escapeHtml(date)}</option>`))
    .join("");

  document.getElementById("channel-filter").value = state.channelFilter;
  document.getElementById("category-filter").value = state.categoryFilter;
  document.getElementById("date-filter").value = state.dateFilter;
  document.getElementById("sort-filter").value = state.sortBy;
  document.getElementById("keyword-filter").value = state.keywordFilter;
}

function sortVideos(videos) {
  const sorted = [...videos];
  switch (state.sortBy) {
    case "views_desc":
      sorted.sort((left, right) => right.view_count - left.view_count);
      break;
    case "engagement_desc":
      sorted.sort((left, right) => right.engagement_rate - left.engagement_rate);
      break;
    case "comments_desc":
      sorted.sort((left, right) => right.comment_count - left.comment_count);
      break;
    case "published_desc":
    default:
      sorted.sort((left, right) => `${right.published_at || ""}`.localeCompare(`${left.published_at || ""}`));
      break;
  }
  return sorted;
}

function filteredVideos() {
  const keyword = state.keywordFilter.trim().toLowerCase();
  return sortVideos(appData.videos.filter((video) => {
    if (state.channelFilter !== "all" && video.channel_key !== state.channelFilter) {
      return false;
    }
    if (state.categoryFilter !== "all" && video.channel_category !== state.categoryFilter) {
      return false;
    }
    if (state.dateFilter !== "all") {
      const dateKey = kstDateKey(video.published_at);
      if (dateKey !== state.dateFilter) {
        return false;
      }
    }
    if (keyword && !video.search_text.includes(keyword)) {
      return false;
    }
    return true;
  }));
}

function groupedFilteredVideos() {
  return groupVideosByDate(filteredVideos()).map((group) => ({
    ...group,
    videos: sortVideos(group.videos),
  }));
}

function selectInitialVideo() {
  if (state.selectedVideoId) {
    const existing = appData.videos.find((video) => video.video_id === state.selectedVideoId);
    if (existing) {
      return;
    }
  }
  state.selectedVideoId = appData.todayVideos[0]?.video_id || appData.videos[0]?.video_id || null;
}

function currentVideo() {
  return appData.videos.find((video) => video.video_id === state.selectedVideoId) || null;
}

function detailSummaryLine(video) {
  const firstHighlight = (video.transcript_highlights || [])[0];
  if (firstHighlight) {
    return truncateText(firstHighlight, 140);
  }
  return truncateText(video.one_line_summary || video.description || "요약 없음", 140);
}

function renderVideoRowPair(video) {
  const tags = uniqueValues([...(video.tools || []), ...(video.topic_tags || [])]).slice(0, 4);
  return `
    <tr class="video-main-row ${state.selectedVideoId === video.video_id ? "is-selected" : ""}">
      <td>
        <button class="text-button js-select-video" data-video-id="${escapeHtml(video.video_id)}" type="button">
          <div class="thumbnail-cell">
            <img class="video-thumb" src="${escapeHtml(video.thumbnail_url)}" alt="">
            <div>
              <p class="video-title">${escapeHtml(video.title)}</p>
              <p class="video-meta-inline">${escapeHtml(video.channel_name)} · ${escapeHtml(formatDuration(video.duration_seconds))}</p>
            </div>
          </div>
        </button>
      </td>
      <td>${escapeHtml(video.channel_name)}</td>
      <td>${escapeHtml(formatDateTime(video.published_at))}</td>
      <td class="metric-cell">${escapeHtml(compactNumber(video.view_count))}</td>
      <td class="metric-cell">${escapeHtml(compactNumber(video.like_count))}</td>
      <td class="metric-cell">${escapeHtml(compactNumber(video.comment_count))}</td>
      <td class="metric-cell metric-cell-wide">
        <strong>${escapeHtml(formatPercent(video.engagement_rate))}</strong>
        <span>좋아요 ${escapeHtml(compactNumber(video.like_count))} · 댓글 ${escapeHtml(compactNumber(video.comment_count))}</span>
      </td>
      <td>${tags.length ? tags.map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join(" ") : '<span class="muted">없음</span>'}</td>
    </tr>
    <tr class="video-summary-row ${state.selectedVideoId === video.video_id ? "is-selected" : ""}">
      <td colspan="8">
        <div class="video-summary-strip">
          <div class="video-summary-block">
            <span class="summary-strip-label">한줄 요약</span>
            <p>${escapeHtml(video.one_line_summary || "요약 없음")}</p>
          </div>
          <div class="video-summary-block small">
            <span class="summary-strip-label">자막 상태</span>
            <p>${escapeHtml(transcriptStatusText(video))}</p>
          </div>
          <div class="video-summary-block">
            <span class="summary-strip-label">핵심 포인트</span>
            <p>${escapeHtml(detailSummaryLine(video))}</p>
          </div>
        </div>
      </td>
    </tr>
  `;
}

function renderDetailView() {
  const groups = groupedFilteredVideos();
  const totalVideos = groups.reduce((sum, group) => sum + group.videos.length, 0);
  const visibleIds = new Set(groups.flatMap((group) => group.videos.map((video) => video.video_id)));
  if (!visibleIds.has(state.selectedVideoId)) {
    state.selectedVideoId = groups[0]?.videos[0]?.video_id || null;
  }
  document.getElementById("detail-count").textContent = `${totalVideos}개`;

  const groupHtml = groups.length
    ? groups.map((group) => `
      <details class="history-group" ${group.is_today || state.dateFilter === group.date ? "open" : ""}>
        <summary class="history-summary">
          <span>${escapeHtml(group.label)}</span>
          <small>${escapeHtml(String(group.video_count))}개 영상</small>
        </summary>
        <div class="table-scroll">
          <table class="notion-table">
            <thead>
              <tr>
                <th>영상</th>
                <th>채널</th>
                <th>업로드 시각</th>
                <th>조회수</th>
                <th>좋아요</th>
                <th>댓글</th>
                <th>참여율</th>
                <th>툴 / 키워드</th>
              </tr>
            </thead>
            <tbody>
              ${group.videos.map(renderVideoRowPair).join("")}
            </tbody>
          </table>
        </div>
      </details>
    `).join("")
    : `<div class="empty-state">조건에 맞는 영상이 없습니다.</div>`;

  document.getElementById("history-groups").innerHTML = groupHtml;
}

function fallbackChannelDetail(channelKey) {
  const channel = appData.channels.find((item) => item.channel_key === channelKey) || null;
  if (!channel) {
    return null;
  }
  const recentVideos = appData.videos
    .filter((video) => video.channel_key === channelKey)
    .sort((left, right) => `${right.published_at || ""}`.localeCompare(`${left.published_at || ""}`))
    .slice(0, 3);
  const topics = uniqueValues(recentVideos.flatMap((video) => video.topic_tags)).slice(0, 5)
    .map((label) => ({ label, video_count: recentVideos.filter((video) => video.topic_tags.includes(label)).length }));
  const recentComments = appData.videos
    .filter((video) => video.channel_key === channelKey)
    .flatMap((video) => video.top_comments || [])
    .sort((left, right) => (right.like_count || 0) - (left.like_count || 0))
    .slice(0, 5);
  return {
    channel,
    recent_videos: recentVideos,
    top_topics: topics,
    recent_comments: recentComments,
  };
}

async function loadChannelDetail(channelKey) {
  if (!channelKey) {
    return null;
  }
  if (state.channelDetailCache.has(channelKey)) {
    return state.channelDetailCache.get(channelKey);
  }
  if (state.apiAvailable) {
    try {
      const response = await fetch(`/api/channel/${encodeURIComponent(channelKey)}`, { cache: "no-store" });
      if (response.ok) {
        const payload = await response.json();
        state.channelDetailCache.set(channelKey, payload);
        return payload;
      }
    } catch (error) {
      state.loadWarnings.push(`채널 상세 로딩 실패: ${error.message}`);
      renderStatusBanner();
    }
  }
  const payload = fallbackChannelDetail(channelKey);
  if (payload) {
    state.channelDetailCache.set(channelKey, payload);
  }
  return payload;
}

async function renderDetailPanel() {
  const video = currentVideo();
  const body = document.getElementById("detail-panel-body");
  if (!video) {
    body.innerHTML = `<div class="empty-state">왼쪽 표에서 영상을 선택하세요.</div>`;
    return;
  }

  const channelDetail = await loadChannelDetail(video.channel_key);
  const comments = (video.top_comments || [])
    .sort((left, right) => (right.like_count || 0) - (left.like_count || 0) || (right.reply_count || 0) - (left.reply_count || 0))
    .slice(0, 5);
  const creatorIdeas = creatorIdeaPoints(video);
  const transcriptHighlights = (video.transcript_highlights || []).slice(0, 5);
  const transcriptBlocks = transcriptParagraphs(video.transcript_text);
  const channelDescription = channelDetail?.channel?.description
    ? channelDescriptionParagraphs(channelDetail.channel.description)
    : [];

  body.innerHTML = `
    <article class="detail-card hero-detail-card">
      <img class="detail-hero-thumb" src="${escapeHtml(video.thumbnail_url)}" alt="">
      <div class="detail-hero-copy">
        <span class="detail-kicker">${escapeHtml(video.channel_name)}</span>
        <h3>${escapeHtml(video.title)}</h3>
        <p class="detail-copy">${escapeHtml(video.one_line_summary || video.description || "요약 없음")}</p>
        <div class="detail-meta">
          <span class="metric-pill">${escapeHtml(video.format)}</span>
          <span class="metric-pill">${escapeHtml(video.hook_type)}</span>
          <span class="metric-pill">${escapeHtml(transcriptStatusText(video))}</span>
        </div>
        <div class="detail-link-row">
          ${video.video_url ? `<a class="detail-link-button" href="${escapeHtml(video.video_url)}" target="_blank" rel="noreferrer">유튜브에서 보기</a>` : ""}
          ${video.channel?.url ? `<a class="detail-link-button secondary" href="${escapeHtml(video.channel.url)}" target="_blank" rel="noreferrer">채널 바로가기</a>` : ""}
        </div>
      </div>
      <div class="metric-grid">
        <div class="metric-box"><span>조회수</span><strong>${escapeHtml(compactNumber(video.view_count))}</strong></div>
        <div class="metric-box"><span>좋아요</span><strong>${escapeHtml(compactNumber(video.like_count))}</strong></div>
        <div class="metric-box"><span>댓글</span><strong>${escapeHtml(compactNumber(video.comment_count))}</strong></div>
        <div class="metric-box"><span>참여율</span><strong>${escapeHtml(formatPercent(video.engagement_rate))}</strong></div>
        <div class="metric-box"><span>업로드 시각</span><strong>${escapeHtml(formatDateTime(video.published_at))}</strong></div>
        <div class="metric-box"><span>길이</span><strong>${escapeHtml(formatDuration(video.duration_seconds))}</strong></div>
      </div>
    </article>

    <article class="detail-card">
      <h3>왜 이 영상이 먹히는가</h3>
      <p class="detail-copy">${escapeHtml(video.why_it_works || "분석 데이터가 아직 없습니다.")}</p>
      ${(video.claims || []).length ? `<ul>${video.claims.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    </article>

    <article class="detail-card">
      <h3>자막 기반 핵심 포인트</h3>
      ${transcriptHighlights.length
        ? `<ul>${transcriptHighlights.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : `<p class="detail-copy">확보된 자막이 없어 설명/메타데이터 중심으로 분석했습니다.</p>`}
      ${transcriptBlocks.length
        ? `
          <details class="transcript-toggle">
            <summary>전체 자막 펼쳐보기</summary>
            <div class="transcript-body">
              ${transcriptBlocks.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}
            </div>
          </details>
        `
        : ""}
    </article>

    <article class="detail-card">
      <h3>내 채널 적용 아이디어</h3>
      ${creatorIdeas.length
        ? `<ul>${creatorIdeas.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : `<p class="detail-copy">적용 아이디어가 아직 없습니다.</p>`}
    </article>

    <article class="detail-card">
      <h3>댓글 반응 상위 5개</h3>
      ${comments.length
        ? `<div class="comment-list">
            ${comments.map((comment) => `
              <div class="comment-item">
                <div class="comment-header">
                  <strong>${escapeHtml(comment.author || "익명")}</strong>
                  <span class="comment-like-pill">👍 ${escapeHtml(compactNumber(comment.like_count))}</span>
                </div>
                <p class="detail-copy">${escapeHtml(comment.text)}</p>
                <div class="comment-meta">답글 ${escapeHtml(compactNumber(comment.reply_count))} · ${escapeHtml(formatDateTime(comment.published_at))}</div>
              </div>
            `).join("")}
          </div>`
        : `<p class="detail-copy">댓글 데이터가 없습니다.</p>`}
    </article>

    <article class="detail-card">
      <h3>채널 상세</h3>
      ${channelDetail && channelDetail.channel ? `
        <div class="channel-hero">
          ${channelDetail.channel.thumbnail_url ? `<img class="channel-avatar" src="${escapeHtml(channelDetail.channel.thumbnail_url)}" alt="">` : `<div class="channel-avatar fallback">${escapeHtml((channelDetail.channel.name || "채널").slice(0, 1))}</div>`}
          <div class="channel-hero-copy">
            <h4>${escapeHtml(channelDetail.channel.name || "알 수 없는 채널")}</h4>
            <p>${escapeHtml(channelDetail.channel.category || "미분류")} · ${escapeHtml(`${channelDetail.channel.country || "미지정"} / ${channelDetail.channel.language || "미지정"}`)}</p>
            ${channelDetail.channel.url ? `<a class="detail-link-button secondary" href="${escapeHtml(channelDetail.channel.url)}" target="_blank" rel="noreferrer">채널 링크 열기</a>` : ""}
          </div>
        </div>
        <div class="channel-meta-list">
          <span class="pill">구독자 ${escapeHtml(compactNumber(channelDetail.channel.subscriber_count))}</span>
          <span class="pill">총 조회수 ${escapeHtml(compactNumber(channelDetail.channel.channel_view_count))}</span>
          <span class="pill">총 영상 수 ${escapeHtml(compactNumber(channelDetail.channel.video_count))}</span>
          <span class="pill">개설일 ${escapeHtml(formatDate(channelDetail.channel.published_at))}</span>
        </div>
        <div class="detail-copy channel-description">
          ${channelDescription.length
            ? `
              <p>${escapeHtml(channelDescription[0])}</p>
              ${channelDescription.length > 1
                ? `
                  <details class="channel-description-toggle">
                    <summary>채널 설명 더보기</summary>
                    ${channelDescription.slice(1).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}
                  </details>
                `
                : ""}
            `
            : "<p>채널 설명이 없습니다.</p>"}
        </div>
        <div class="recent-channel-videos">
          ${(channelDetail.recent_videos || []).map((item) => `
            <a class="recent-channel-video" href="${escapeHtml(item.video_url || "#")}" target="_blank" rel="noreferrer">
              <img src="${escapeHtml(item.thumbnail_url || "")}" alt="">
              <div>
                <strong>${escapeHtml(item.title || "제목 없음")}</strong>
                <span>${escapeHtml(formatDateTime(item.published_at))}</span>
              </div>
            </a>
          `).join("") || '<span class="muted">최근 업로드 정보가 없습니다.</span>'}
        </div>
      ` : `<p class="detail-copy">채널 상세 데이터를 불러오지 못했습니다.</p>`}
    </article>
  `;
}

function renderWatchlistView() {
  document.getElementById("watchlist-count").textContent = `${appData.channels.length}개`;
  document.getElementById("watchlist-table-body").innerHTML = appData.channels.length
    ? appData.channels.map((channel) => `
      <tr>
        <td>${escapeHtml(channel.name)}</td>
        <td>${escapeHtml(channel.category)}</td>
        <td>
          <span class="status-chip ${channel.is_active ? "active" : "inactive"}">
            ${channel.is_active ? "활성" : "비활성"}
          </span>
        </td>
        <td>${escapeHtml(compactNumber(channel.subscriber_count))}</td>
        <td>${escapeHtml(compactNumber(channel.channel_view_count))}</td>
        <td>${escapeHtml(compactNumber(channel.video_count))}</td>
        <td>${escapeHtml(formatDateTime(channel.last_synced_at))}</td>
        <td>${channel.url ? `<a href="${escapeHtml(channel.url)}" target="_blank" rel="noreferrer">채널 열기</a>` : '<span class="muted">없음</span>'}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="8"><div class="empty-state">등록된 채널이 없습니다.</div></td></tr>`;
}

function renderAll() {
  renderStatusBanner();
  renderTopMeta();
  renderSummaryView();
  populateFilters();
  renderDetailView();
  renderWatchlistView();
  actionButtonsState();
  selectInitialVideo();
  renderDetailPanel();
}

function activateView(target) {
  state.view = target;
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.viewTarget === target);
  });
  document.querySelectorAll(".view-section").forEach((section) => {
    section.classList.toggle("is-active", section.id === `${target}-view`);
  });
}

async function refreshFromApi(actionLabel) {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.apiAvailable = true;
    state.previewMode = false;
    appData.channels = normalizeWatchlistPayload(payload.channels || []);
    appData.videos = hydrateVideos(normalizeVideoPayload(payload.videos || []));
    appData.todayVideos = hydrateVideos(normalizeVideoPayload(payload.todayVideos || []));
    appData.groupedHistory = groupVideosByDate(appData.videos);
    appData.digest = normalizeDigestPayload(payload.digest || {});
    if (actionLabel) {
      state.loadWarnings = [`${actionLabel} 완료`];
    }
    renderAll();
  } catch (error) {
    state.loadWarnings = [`${actionLabel || "데이터 새로고침"} 실패: ${error.message}`];
    renderStatusBanner();
  }
}

async function handleImportNotion() {
  if (!state.apiAvailable) {
    state.loadWarnings = [READ_ONLY_MESSAGE];
    renderStatusBanner();
    return;
  }
  try {
    const response = await fetch("/api/watchlist/import-notion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notion_url: currentNotionSourceUrl() }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    state.loadWarnings = (payload.warnings || []).length ? payload.warnings : ["Notion 워치리스트를 다시 가져왔습니다."];
    await refreshFromApi();
  } catch (error) {
    state.loadWarnings = [`Notion 가져오기 실패: ${error.message}`];
    renderStatusBanner();
  }
}

async function handleRunPipeline() {
  if (!state.apiAvailable) {
    state.loadWarnings = [READ_ONLY_MESSAGE];
    renderStatusBanner();
    return;
  }
  try {
    state.loadWarnings = ["업데이트를 실행 중입니다. 잠시만 기다려주세요."];
    renderStatusBanner();
    const response = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notify_telegram: false, notion_url: currentNotionSourceUrl() }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.stderr || payload.error || `HTTP ${response.status}`);
    }
    state.loadWarnings = ["업데이트 실행이 완료되었습니다."];
    await refreshFromApi();
  } catch (error) {
    state.loadWarnings = [`업데이트 실행 실패: ${error.message}`];
    renderStatusBanner();
  }
}

function openVideoDetail(videoId) {
  if (!videoId) {
    return;
  }
  state.selectedVideoId = videoId;
  activateView("detail");
  renderDetailView();
  renderDetailPanel();
}

function bindEvents() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => activateView(button.dataset.viewTarget));
  });

  document.getElementById("channel-filter").addEventListener("change", (event) => {
    state.channelFilter = event.target.value;
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("category-filter").addEventListener("change", (event) => {
    state.categoryFilter = event.target.value;
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("date-filter").addEventListener("change", (event) => {
    state.dateFilter = event.target.value;
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("sort-filter").addEventListener("change", (event) => {
    state.sortBy = event.target.value;
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("keyword-filter").addEventListener("input", (event) => {
    state.keywordFilter = event.target.value;
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("reset-filters").addEventListener("click", () => {
    state.channelFilter = "all";
    state.categoryFilter = "all";
    state.dateFilter = "all";
    state.sortBy = "published_desc";
    state.keywordFilter = "";
    document.getElementById("channel-filter").value = "all";
    document.getElementById("category-filter").value = "all";
    document.getElementById("date-filter").value = "all";
    document.getElementById("sort-filter").value = "published_desc";
    document.getElementById("keyword-filter").value = "";
    renderDetailView();
    renderDetailPanel();
  });
  document.getElementById("import-notion-button").addEventListener("click", handleImportNotion);
  document.getElementById("run-pipeline-button").addEventListener("click", handleRunPipeline);

  document.addEventListener("click", (event) => {
    const selectTarget = event.target.closest(".js-select-video");
    if (selectTarget) {
      state.selectedVideoId = selectTarget.dataset.videoId;
      renderDetailView();
      renderDetailPanel();
      return;
    }

    const openTarget = event.target.closest(".js-open-video");
    if (openTarget) {
      openVideoDetail(openTarget.dataset.videoId);
    }
  });
}

async function bootstrap() {
  await loadBootstrap();
  renderAll();
  bindEvents();
}

bootstrap();
