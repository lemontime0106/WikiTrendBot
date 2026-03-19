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
const productList = document.getElementById("productList");
const tagList = document.getElementById("tagList");
const manualKeywordInput = document.getElementById("manualKeywordInput");
const manualGenerateButton = document.getElementById("manualGenerateButton");

let selectedKeyword = "";
let currentArticleMarkdown = "";
let currentTags = [];
let isEditMode = false;
let currentMode = "trend";

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderMarkdown(markdown) {
  const lines = markdown.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let listItems = [];

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
    const line = escapeHtml(rawLine.trim());

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    if (line.startsWith("### ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h3>${line.slice(4)}</h3>`);
      return;
    }

    if (line.startsWith("## ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h2>${line.slice(3)}</h2>`);
      return;
    }

    if (line.startsWith("# ")) {
      flushParagraph();
      flushList();
      blocks.push(`<h1>${line.slice(2)}</h1>`);
      return;
    }

    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(line.slice(2));
      return;
    }

    flushList();
    paragraph.push(line);
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
      return `
        <article class="support-card">
          <strong class="support-card-title">${title}</strong>
          <div>${snippet || "요약 없음"}</div>
          <div class="support-card-meta">${source || "출처 정보 없음"}</div>
        </article>
      `;
    })
    .join("");
}

function renderProductRecommendations(items) {
  if (!Array.isArray(items) || !items.length) {
    productList.className = "support-list empty-state";
    productList.textContent = "연관 추천 상품이 없습니다.";
    return;
  }

  productList.className = "support-list";
  productList.innerHTML = items
    .map(
      (item) => `
        <article class="support-card">
          <strong class="support-card-title">${escapeHtml(item)}</strong>
          <div class="support-card-meta">글 본문과 분리된 별도 추천 상품</div>
        </article>
      `
    )
    .join("");
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

function syncEditor(markdown) {
  currentArticleMarkdown = markdown;
  articleEditor.value = markdown;
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
  articleMeta.textContent = `"${keyword}" 키워드로 글을 생성 중입니다.`;
  articleOutput.classList.remove("empty-state");
  articleOutput.innerHTML = "글을 생성하고 있습니다...";
  syncEditor("");
  renderSearchResults([]);
  renderProductRecommendations([]);
  renderRecommendedTags([]);
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
  renderProductRecommendations([]);
  renderRecommendedTags([]);
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
      body: JSON.stringify({ keyword }),
    });
    const data = await parseResponse(response);

    if (!response.ok) {
      throw new Error(data.detail || "글 생성에 실패했습니다.");
    }

    modelBadge.textContent = data.model || "모델 정보 없음";
    articleMeta.textContent = `선택 키워드: ${data.selected_keyword}`;
    articleOutput.className = "article-output";
    syncEditor(data.article_markdown || "");
    articleOutput.innerHTML = renderMarkdown(currentArticleMarkdown);
    renderSearchResults(data.search_results || []);
    renderProductRecommendations(data.product_recommendations || []);
    renderRecommendedTags(data.recommended_tags || []);
    setToolbarState({
      copyDisabled: false,
      editDisabled: false,
      message: "생성된 글을 복사하거나 바로 수정할 수 있습니다.",
    });
    setStatus(`"${keyword}" 키워드 글 생성을 마쳤습니다.`);
  } catch (error) {
    articleMeta.textContent = `선택 키워드: ${keyword}`;
    articleOutput.className = "article-output empty-state";
    articleOutput.textContent = error.message;
    syncEditor("");
    renderSearchResults([]);
    renderProductRecommendations([]);
    renderRecommendedTags([]);
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
  copyStatusText.textContent = "수정한 내용을 미리보기에 반영했습니다.";
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
