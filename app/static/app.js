const loadTrendsButton = document.getElementById("loadTrendsButton");
const trendModeButton = document.getElementById("trendModeButton");
const manualModeButton = document.getElementById("manualModeButton");
const trendModePanel = document.getElementById("trendModePanel");
const manualModePanel = document.getElementById("manualModePanel");
const trendList = document.getElementById("trendList");
const trendCountBadge = document.getElementById("trendCountBadge");
const statusText = document.getElementById("statusText");
const modelBadge = document.getElementById("modelBadge");
const articleMeta = document.getElementById("articleMeta");
const articleOutput = document.getElementById("articleOutput");
const copyArticleButton = document.getElementById("copyArticleButton");
const copyTagsButton = document.getElementById("copyTagsButton");
const toggleEditButton = document.getElementById("toggleEditButton");
const copyStatusText = document.getElementById("copyStatusText");
const editorSection = document.getElementById("editorSection");
const articleEditor = document.getElementById("articleEditor");
const previewArticleButton = document.getElementById("previewArticleButton");
const searchContextList = document.getElementById("searchContextList");
const tagList = document.getElementById("tagList");
const imagePromptList = document.getElementById("imagePromptList");
const publishTitleInput = document.getElementById("publishTitleInput");
const publishTagsInput = document.getElementById("publishTagsInput");
const uploadToTistoryButton = document.getElementById("uploadToTistoryButton");
const publishStatusText = document.getElementById("publishStatusText");
const manualKeywordInput = document.getElementById("manualKeywordInput");
const manualGenerateButton = document.getElementById("manualGenerateButton");
const qualityCheckButton = document.getElementById("qualityCheckButton");
const qualityScoreBadge = document.getElementById("qualityScoreBadge");
const qualityReportList = document.getElementById("qualityReportList");

let selectedKeyword = "";
let currentArticleMarkdown = "";
let currentTags = [];
let currentImagePrompts = [];
let currentImageFiles = [];
let currentPublishTitle = "";
let isEditMode = false;
let currentMode = "trend";
let currentQualityPassed = false;

const IMAGE_PROMPT_PATTERN = /^\[여기에 들어갈 이미지 생성 프롬프트:\s*(.+?)\]\s*$/;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function renderInlineMarkdown(value) {
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  const chunks = [];
  let cursor = 0;
  let match;

  while ((match = pattern.exec(value)) !== null) {
    chunks.push(escapeHtml(value.slice(cursor, match.index)));
    chunks.push(
      `<a href="${escapeAttribute(match[2])}" target="_blank" rel="noopener noreferrer">${escapeHtml(match[1])}</a>`
    );
    cursor = match.index + match[0].length;
  }
  chunks.push(escapeHtml(value.slice(cursor)));
  return chunks.join("");
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let listItems = [];
  let imageSlotCount = 0;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    blocks.push(`<p>${paragraph.join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) {
      return;
    }
    blocks.push(`<ul>${listItems.map((item) => `<li>${item}</li>`).join("")}</ul>`);
    listItems = [];
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    const imagePromptMatch = rawLine.trim().match(IMAGE_PROMPT_PATTERN);
    if (imagePromptMatch) {
      flushParagraph();
      flushList();
      imageSlotCount += 1;
      blocks.push(`
        <div class="image-slot-preview">
          <div class="image-slot-preview-label">이미지 슬롯 ${imageSlotCount}</div>
          <div>${escapeHtml(imagePromptMatch[1])}</div>
        </div>
      `);
      return;
    }

    if (line.startsWith("### ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h3>${renderInlineMarkdown(line.slice(4))}</h3>`);
      return;
    }

    if (line.startsWith("## ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h2>${renderInlineMarkdown(line.slice(3))}</h2>`);
      return;
    }

    if (line.startsWith("# ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h1>${renderInlineMarkdown(line.slice(2))}</h1>`);
      return;
    }

    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(renderInlineMarkdown(line.slice(2)));
      return;
    }

    flushList();
    paragraph.push(renderInlineMarkdown(line));
  });

  flushParagraph();
  flushList();

  return blocks.join("");
}

function setStatus(message) {
  statusText.textContent = message;
}

function switchMode(mode) {
  currentMode = mode;
  const isTrendMode = mode === "trend";

  trendModeButton.classList.toggle("is-active", isTrendMode);
  manualModeButton.classList.toggle("is-active", !isTrendMode);
  trendModePanel.classList.toggle("hidden", !isTrendMode);
  manualModePanel.classList.toggle("hidden", isTrendMode);

  if (isTrendMode) {
    setStatus("트렌드 키워드를 선택해 글을 생성할 수 있습니다.");
  } else {
    setStatus("직접 입력한 키워드로 글을 생성할 수 있습니다.");
    manualKeywordInput.focus();
  }
}

function setToolbarState({ copyDisabled, editDisabled, message }) {
  copyArticleButton.disabled = copyDisabled;
  copyTagsButton.disabled = copyDisabled;
  toggleEditButton.disabled = editDisabled;
  copyStatusText.textContent = message;
}

function formatPublishSteps(steps) {
  if (!Array.isArray(steps) || !steps.length) {
    return "";
  }
  return steps.map((item) => item.message || item.step).filter(Boolean).join(" / ");
}

function renderSearchResults(items) {
  if (!Array.isArray(items) || !items.length) {
    searchContextList.className = "support-list empty-state";
    searchContextList.textContent = "검색 참고 정보가 없습니다.";
    return;
  }

  searchContextList.className = "support-list";
  searchContextList.innerHTML = items
    .map((item) => {
      const title = escapeHtml(item.title || "");
      const snippet = escapeHtml(item.snippet || "");
      const source = escapeHtml(item.source || "");
      const url = typeof item.url === "string" ? item.url.trim() : "";
      const link = url
        ? `<a class="support-card-link" href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">원문 확인</a>`
        : "";
      return `
        <article class="support-card">
          <strong class="support-card-title">${title}</strong>
          <div>${snippet || "요약 없음"}</div>
          <div class="support-card-meta">${source || "출처 정보 없음"} ${link}</div>
        </article>
      `;
    })
    .join("");
}

function renderQualityReport(report, invalidationMessage = "") {
  const checks = Array.isArray(report?.checks) ? report.checks : [];
  currentQualityPassed = Boolean(report?.passed);
  qualityScoreBadge.className = `badge ${
    currentQualityPassed ? "quality-pass" : checks.length ? "quality-fail" : "subtle"
  }`;
  qualityScoreBadge.textContent = checks.length
    ? `${currentQualityPassed ? "통과" : "차단"} ${Number(report.score || 0)}점`
    : "검사 전";

  if (!checks.length) {
    qualityReportList.className = "support-list empty-state";
    qualityReportList.textContent =
      invalidationMessage ||
      "글을 생성하면 출처·직접 경험·중복·편집 품질 검사 결과가 표시됩니다.";
    updatePublishForm({
      markdown: articleEditor.value || currentArticleMarkdown,
      tags: currentTags,
      keepUserTitle: true,
    });
    return;
  }

  const reasons = Array.isArray(report.blocking_reasons)
    ? report.blocking_reasons
    : [];
  qualityReportList.className = "support-list quality-report-list";
  qualityReportList.innerHTML = `
    ${
      reasons.length
        ? `<div class="quality-blocking-summary"><strong>발행 차단 사유</strong>${reasons
            .map((reason) => `<div>• ${escapeHtml(reason)}</div>`)
            .join("")}</div>`
        : '<div class="quality-success-summary">필수 품질 기준을 모두 통과했습니다.</div>'
    }
    <div class="quality-check-grid">
      ${checks
        .map(
          (check) => `
            <article class="quality-check-card ${check.passed ? "is-pass" : "is-fail"}">
              <div class="quality-check-heading">
                <strong>${escapeHtml(check.label || check.code || "품질 항목")}</strong>
                <span>${check.passed ? "통과" : check.blocking ? "차단" : "경고"}</span>
              </div>
              <div>${escapeHtml(check.detail || "")}</div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
  updatePublishForm({
    markdown: articleEditor.value || currentArticleMarkdown,
    tags: currentTags,
    keepUserTitle: true,
  });
}

function renderRecommendedTags(items) {
  currentTags = Array.isArray(items) ? items : [];

  if (!currentTags.length) {
    tagList.className = "support-list empty-state";
    tagList.textContent = "추천 태그가 없습니다.";
    return;
  }

  tagList.className = "support-list";
  tagList.innerHTML = `
    <div class="tag-chip-wrap">
      ${currentTags.map((tag) => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join("")}
    </div>
  `;
}

function extractTitleFromMarkdown(markdown) {
  const titleLine = markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.startsWith("# "));
  return titleLine ? titleLine.slice(2).trim() : "";
}

function updatePublishForm({ markdown, tags, keepUserTitle = false }) {
  const extractedTitle = extractTitleFromMarkdown(markdown || "");
  currentPublishTitle = extractedTitle;

  if (!keepUserTitle || !publishTitleInput.value.trim()) {
    publishTitleInput.value = extractedTitle;
  }

  if (Array.isArray(tags)) {
    publishTagsInput.value = tags.join(", ");
  }

  const hasArticle = Boolean((markdown || "").trim());
  qualityCheckButton.disabled = !hasArticle;
  uploadToTistoryButton.disabled = !hasArticle || !currentQualityPassed;

  if (!hasArticle) {
    publishStatusText.textContent =
      "글 생성 후 제목, 태그, 이미지 파일을 확인한 다음 업로드할 수 있습니다.";
  } else if (!currentQualityPassed) {
    publishStatusText.textContent =
      "현재 본문은 품질 검사를 통과하지 않았습니다. 차단 사유를 수정한 뒤 다시 검사하세요.";
  }
}

function normalizeImagePromptItem(item, index) {
  if (!item || typeof item !== "object") {
    return null;
  }

  const prompt = typeof item.prompt === "string" ? item.prompt.trim() : "";
  if (!prompt) {
    return null;
  }

  const slot = Number.isInteger(item.slot) ? item.slot : index + 1;
  return {
    slot,
    prompt,
    placeholder:
      typeof item.placeholder === "string" && item.placeholder.trim()
        ? item.placeholder.trim()
        : `[여기에 들어갈 이미지 생성 프롬프트: ${prompt}]`,
    line: Number.isInteger(item.line) ? item.line : null,
  };
}

function extractImagePromptsFromMarkdown(markdown) {
  return markdown
    .split(/\r?\n/)
    .map((line, index) => {
      const match = line.trim().match(IMAGE_PROMPT_PATTERN);
      if (!match) {
        return null;
      }
      return {
        slot: index + 1,
        prompt: match[1].trim(),
        placeholder: line.trim(),
        line: index + 1,
      };
    })
    .filter(Boolean)
    .map((item, index) => ({
      ...item,
      slot: index + 1,
    }));
}

function renderImagePrompts(items) {
  currentImagePrompts = Array.isArray(items) ? items : [];
  currentImageFiles = currentImagePrompts.map((_, index) => currentImageFiles[index] || null);

  if (!currentImagePrompts.length) {
    imagePromptList.className = "support-list empty-state";
    imagePromptList.textContent = "이미지 자리표시자가 없습니다.";
    return;
  }

  imagePromptList.className = "support-list image-slot-list";
  imagePromptList.innerHTML = currentImagePrompts
    .map((item, index) => {
      const file = currentImageFiles[index];
      const lineText = item.line ? `본문 ${item.line}번째 줄` : "본문 위치 정보 없음";
      return `
        <article class="image-slot-card" data-slot-index="${index}">
          <div class="image-slot-card-top">
            <span class="badge">슬롯 ${item.slot}</span>
            <span class="image-slot-line">${lineText}</span>
          </div>
          <div class="image-slot-prompt">${escapeHtml(item.prompt)}</div>
          <label class="image-slot-upload">
            <span>이 슬롯에 넣을 이미지 파일</span>
            <input class="image-slot-input" type="file" accept="image/*" data-slot-index="${index}">
          </label>
          <div class="image-slot-file-name">${file ? escapeHtml(file.name) : "아직 연결된 파일이 없습니다."}</div>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll(".image-slot-input").forEach((input) => {
    input.addEventListener("change", (event) => {
      const index = Number(event.currentTarget.dataset.slotIndex);
      const file = event.currentTarget.files?.[0] || null;
      currentImageFiles[index] = file;

      const fileNameNode = event.currentTarget
        .closest(".image-slot-card")
        ?.querySelector(".image-slot-file-name");
      if (fileNameNode) {
        fileNameNode.textContent = file ? file.name : "아직 연결된 파일이 없습니다.";
      }

      copyStatusText.textContent = file
        ? `슬롯 ${index + 1}에 이미지 파일을 연결했습니다.`
        : `슬롯 ${index + 1}의 이미지 연결을 비웠습니다.`;
      publishStatusText.textContent = file
        ? `슬롯 ${index + 1} 이미지가 연결되었습니다. 업로드를 진행할 수 있습니다.`
        : `슬롯 ${index + 1} 이미지 연결이 비워졌습니다.`;
    });
  });
}

function syncEditor(markdown) {
  currentArticleMarkdown = markdown;
  articleEditor.value = markdown;
  updatePublishForm({ markdown, tags: currentTags, keepUserTitle: false });
}

function openEditor() {
  isEditMode = true;
  editorSection.classList.remove("hidden");
  toggleEditButton.textContent = "수정 닫기";
}

function closeEditor() {
  isEditMode = false;
  editorSection.classList.add("hidden");
  toggleEditButton.textContent = "수정하기";
}

async function parseResponse(response) {
  const text = await response.text();

  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { detail: text || "응답을 해석하지 못했습니다." };
  }
}

function setArticleLoading(keyword) {
  articleMeta.textContent = `"${keyword}" 키워드의 독자와 글 방향을 기획하고 있습니다.`;
  articleOutput.classList.remove("empty-state");
  articleOutput.innerHTML = "글을 생성하고 있습니다...";
  syncEditor("");
  renderSearchResults([]);
  renderRecommendedTags([]);
  renderImagePrompts([]);
  renderQualityReport(null);
  updatePublishForm({ markdown: "", tags: [] });
  closeEditor();
  setToolbarState({
    copyDisabled: true,
    editDisabled: true,
    message: "생성이 끝나면 복사와 수정이 가능합니다.",
  });
}

function renderTrends(trends) {
  selectedKeyword = "";
  trendCountBadge.textContent = `${trends.length}개`;

  if (!trends.length) {
    trendList.className = "keyword-list empty-state";
    trendList.textContent = "가져온 키워드가 없습니다.";
    return;
  }

  trendList.className = "keyword-list";
  trendList.innerHTML = trends
    .map(
      (keyword, index) => `
        <button class="keyword-button" data-keyword="${escapeHtml(keyword)}" type="button">
          <span class="keyword-rank">${String(index + 1).padStart(2, "0")}</span>
          <span>${escapeHtml(keyword)}</span>
        </button>
      `
    )
    .join("");

  document.querySelectorAll(".keyword-button").forEach((button) => {
    button.addEventListener("click", () => {
      const keyword = button.dataset.keyword || "";
      selectedKeyword = keyword;

      document.querySelectorAll(".keyword-button").forEach((item) => {
        item.classList.remove("is-selected");
        item.disabled = true;
      });
      button.classList.add("is-selected");

      generateArticle(keyword);
    });
  });
}

async function loadTrends() {
  loadTrendsButton.disabled = true;
  trendList.className = "keyword-list empty-state";
  trendList.textContent = "키워드를 불러오고 있습니다...";
  setStatus("최신 트렌드 키워드를 가져오는 중입니다.");
  articleMeta.textContent = "새 키워드를 선택하면 결과가 여기에 표시됩니다.";
  articleOutput.className = "article-output empty-state";
  articleOutput.textContent = "아직 생성된 글이 없습니다.";
  modelBadge.textContent = "모델 대기 중";
  syncEditor("");
  renderSearchResults([]);
  renderRecommendedTags([]);
  renderImagePrompts([]);
  renderQualityReport(null);
  updatePublishForm({ markdown: "", tags: [] });
  closeEditor();
  setToolbarState({
    copyDisabled: true,
    editDisabled: true,
    message: "생성 후 복사와 수정이 가능합니다.",
  });

  try {
    const response = await fetch("/trend");
    const data = await parseResponse(response);

    if (!response.ok) {
      throw new Error(data.detail || "키워드를 가져오지 못했습니다.");
    }

    const trends = Array.isArray(data.trends) ? data.trends : [];
    renderTrends(trends);
    setStatus("키워드를 불러왔습니다. 원하는 항목을 눌러 글을 생성하세요.");
  } catch (error) {
    trendCountBadge.textContent = "0개";
    trendList.className = "keyword-list empty-state";
    trendList.textContent = error.message;
    setStatus("키워드 조회에 실패했습니다.");
  } finally {
    loadTrendsButton.disabled = false;
  }
}

async function generateArticle(keyword) {
  setArticleLoading(keyword);
  setStatus(`"${keyword}" 키워드로 글을 생성하고 있습니다.`);
  manualGenerateButton.disabled = true;

  try {
    const response = await fetch("/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        keyword,
      }),
    });
    const data = await parseResponse(response);

    if (!response.ok) {
      throw new Error(data.detail || "글 생성에 실패했습니다.");
    }

    modelBadge.textContent = data.model || "모델 정보 없음";
    const revisionText = Number(data.revision_count || 0)
      ? ` / 자동 수정 ${data.revision_count}회`
      : "";
    const readerOutcome = data.article_plan?.reader_outcome || "";
    articleMeta.textContent = readerOutcome
      ? `선택 키워드: ${data.selected_keyword} / 독자 목표: ${readerOutcome}${revisionText}`
      : `선택 키워드: ${data.selected_keyword}${revisionText}`;
    articleOutput.className = "article-output";
    syncEditor(data.article_markdown || "");
    articleOutput.innerHTML = renderMarkdown(currentArticleMarkdown);
    renderSearchResults(data.search_results || []);
    renderRecommendedTags(data.recommended_tags || []);
    renderQualityReport(data.quality_report || null);
    updatePublishForm({ markdown: data.article_markdown || "", tags: data.recommended_tags || [] });
    const imagePrompts = Array.isArray(data.image_prompts) && data.image_prompts.length
      ? data.image_prompts.map(normalizeImagePromptItem).filter(Boolean)
      : extractImagePromptsFromMarkdown(data.article_markdown || "");
    renderImagePrompts(imagePrompts);
    setToolbarState({
      copyDisabled: false,
      editDisabled: false,
      message: currentQualityPassed
        ? "품질 검사를 통과했습니다. 최종 내용을 직접 확인하세요."
        : "발행 차단 사유를 확인하고 글을 수정한 뒤 다시 검사하세요.",
    });
    setStatus(`"${keyword}" 키워드 글 생성을 마쳤습니다.`);
  } catch (error) {
    articleMeta.textContent = `선택 키워드: ${keyword}`;
    articleOutput.className = "article-output empty-state";
    articleOutput.textContent = error.message;
    syncEditor("");
    renderSearchResults([]);
    renderRecommendedTags([]);
    renderImagePrompts([]);
    renderQualityReport(null);
    updatePublishForm({ markdown: "", tags: [] });
    closeEditor();
    setToolbarState({
      copyDisabled: true,
      editDisabled: true,
      message: "오류가 해결되면 다시 시도해 주세요.",
    });
    setStatus("글 생성에 실패했습니다.");
  } finally {
    manualGenerateButton.disabled = false;
    document.querySelectorAll(".keyword-button").forEach((item) => {
      item.disabled = false;
      item.classList.toggle("is-selected", item.dataset.keyword === selectedKeyword);
    });
  }
}

copyArticleButton.addEventListener("click", async () => {
  if (!currentArticleMarkdown) {
    return;
  }

  try {
    await navigator.clipboard.writeText(articleEditor.value || currentArticleMarkdown);
    copyStatusText.textContent = "글을 클립보드에 복사했습니다.";
  } catch {
    copyStatusText.textContent = "복사에 실패했습니다. 브라우저 권한을 확인해 주세요.";
  }
});

copyTagsButton.addEventListener("click", async () => {
  if (!currentTags.length) {
    return;
  }

  try {
    await navigator.clipboard.writeText(currentTags.join(", "));
    copyStatusText.textContent = "태그를 클립보드에 복사했습니다.";
  } catch {
    copyStatusText.textContent = "태그 복사에 실패했습니다. 브라우저 권한을 확인해 주세요.";
  }
});

toggleEditButton.addEventListener("click", () => {
  if (toggleEditButton.disabled) {
    return;
  }

  if (isEditMode) {
    closeEditor();
    copyStatusText.textContent = "수정 화면을 닫았습니다.";
    return;
  }

  openEditor();
  copyStatusText.textContent = "수정 모드입니다. 내용을 바꾼 뒤 미리보기를 눌러 반영하세요.";
});

previewArticleButton.addEventListener("click", () => {
  currentArticleMarkdown = articleEditor.value;
  articleOutput.className = "article-output";
  articleOutput.innerHTML = renderMarkdown(currentArticleMarkdown);
  renderImagePrompts(extractImagePromptsFromMarkdown(currentArticleMarkdown));
  renderQualityReport(null, "본문이 수정되어 기존 승인이 취소됐습니다. 품질 검사를 다시 실행하세요.");
  updatePublishForm({ markdown: currentArticleMarkdown, tags: currentTags, keepUserTitle: true });
  copyStatusText.textContent = "수정 내용을 반영했습니다. 발행 전 품질 검사를 다시 실행하세요.";
});

articleEditor.addEventListener("input", () => {
  if (!currentQualityPassed) {
    return;
  }
  renderQualityReport(
    null,
    "본문이 수정되어 기존 승인이 취소됐습니다. 품질 검사를 다시 실행하세요."
  );
  copyStatusText.textContent = "본문이 변경됐습니다. 발행 전 품질 검사를 다시 실행하세요.";
});

qualityCheckButton.addEventListener("click", async () => {
  const articleMarkdown = articleEditor.value || currentArticleMarkdown;
  if (!articleMarkdown.trim()) {
    return;
  }

  qualityCheckButton.disabled = true;
  uploadToTistoryButton.disabled = true;
  qualityScoreBadge.className = "badge subtle";
  qualityScoreBadge.textContent = "검사 중";
  copyStatusText.textContent = "수정된 본문의 사실 근거와 품질을 다시 검사하고 있습니다.";

  try {
    const response = await fetch("/quality-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_markdown: articleMarkdown,
        firsthand_notes: "",
      }),
    });
    const data = await parseResponse(response);
    if (!response.ok) {
      throw new Error(data.detail || "품질 검사에 실패했습니다.");
    }
    currentArticleMarkdown = articleMarkdown;
    renderQualityReport(data);
    copyStatusText.textContent = currentQualityPassed
      ? "품질 검사를 통과했습니다. 최종 사실관계를 직접 확인한 뒤 업로드하세요."
      : "품질 검사에서 차단됐습니다. 표시된 사유를 수정하세요.";
  } catch (error) {
    renderQualityReport(null, error.message);
    copyStatusText.textContent = error.message;
  } finally {
    qualityCheckButton.disabled = !articleMarkdown.trim();
  }
});

uploadToTistoryButton.addEventListener("click", async () => {
  const articleMarkdown = articleEditor.value || currentArticleMarkdown;
  const title = publishTitleInput.value.trim() || currentPublishTitle;
  const tagsText = publishTagsInput.value.trim();
  const imagePrompts = extractImagePromptsFromMarkdown(articleMarkdown);

  if (!articleMarkdown.trim()) {
    publishStatusText.textContent = "업로드할 글이 없습니다.";
    return;
  }
  if (!currentQualityPassed) {
    publishStatusText.textContent =
      "현재 본문은 품질 검사를 통과하지 않았습니다. 먼저 품질 검사를 실행하세요.";
    return;
  }

  const missingSlots = imagePrompts
    .map((item, index) => ({ slot: item.slot, file: currentImageFiles[index] || null }))
    .filter((item) => !item.file)
    .map((item) => item.slot);

  if (missingSlots.length) {
    publishStatusText.textContent = `이미지 슬롯 ${missingSlots.join(", ")}에 파일을 연결해 주세요.`;
    return;
  }

  uploadToTistoryButton.disabled = true;
  publishStatusText.textContent = "브라우저를 열어 티스토리 업로드를 진행하고 있습니다. 로그인 화면이 보이면 로그인해 주세요.";

  try {
    const formData = new FormData();
    formData.append("article_markdown", articleMarkdown);
    formData.append("title", title);
    formData.append("tags", tagsText);

    imagePrompts.forEach((item, index) => {
      const file = currentImageFiles[index];
      if (!file) {
        return;
      }
      formData.append("image_slot_numbers", String(item.slot));
      formData.append("image_files", file, file.name);
    });

    const response = await fetch("/publish", {
      method: "POST",
      body: formData,
    });
    const data = await parseResponse(response);

    if (!response.ok) {
      throw new Error(data.detail || "티스토리 업로드에 실패했습니다.");
    }

    const stepText = formatPublishSteps(data.status_steps);
    const suffix = stepText ? ` 진행 단계: ${stepText}` : "";
    if (data.status === "WAITING_FINAL_APPROVAL") {
      publishStatusText.textContent = `${data.message || "티스토리 입력을 완료했습니다. 브라우저에서 최종 발행을 확인해 주세요."}${suffix}`;
    } else if (data.status === "UNKNOWN_RESULT") {
      publishStatusText.textContent = data.post_url
        ? `발행 결과를 확정하지 못했습니다. 현재 주소: ${data.post_url}${suffix}`
        : `발행 결과를 확정하지 못했습니다.${suffix}`;
    } else {
      publishStatusText.textContent = data.post_url
        ? `업로드를 완료했습니다. 게시 주소: ${data.post_url}${suffix}`
        : `티스토리 업로드를 완료했습니다.${suffix}`;
    }
  } catch (error) {
    publishStatusText.textContent = error.message;
  } finally {
    uploadToTistoryButton.disabled = !articleMarkdown.trim() || !currentQualityPassed;
  }
});

trendModeButton.addEventListener("click", () => {
  switchMode("trend");
});

manualModeButton.addEventListener("click", () => {
  switchMode("manual");
});

manualGenerateButton.addEventListener("click", () => {
  const keyword = manualKeywordInput.value.trim();
  if (!keyword) {
    setStatus("직접 입력할 키워드를 먼저 작성해 주세요.");
    manualKeywordInput.focus();
    return;
  }

  document.querySelectorAll(".keyword-button").forEach((item) => {
    item.classList.remove("is-selected");
  });
  selectedKeyword = "";
  generateArticle(keyword);
});

manualKeywordInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    manualGenerateButton.click();
  }
});

loadTrendsButton.addEventListener("click", loadTrends);
