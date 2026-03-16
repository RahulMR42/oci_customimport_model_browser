const searchInput = document.getElementById("searchInput");
const searchButton = document.getElementById("searchButton");
const refreshButton = document.getElementById("refreshButton");
const greyThemeButton = document.getElementById("greyThemeButton");
const darkThemeButton = document.getElementById("darkThemeButton");
const familyCount = document.getElementById("familyCount");
const modelCount = document.getElementById("modelCount");
const generatedAt = document.getElementById("generatedAt");
const feedback = document.getElementById("feedback");
const crawlPages = document.getElementById("crawlPages");
const results = document.getElementById("results");
const familyTemplate = document.getElementById("familyTemplate");
const THEME_STORAGE_KEY = "customimport-theme";

function applyTheme(theme) {
  const resolvedTheme = theme === "dark" ? "dark" : "grey";
  document.documentElement.dataset.theme = resolvedTheme;
  window.localStorage.setItem(THEME_STORAGE_KEY, resolvedTheme);
  greyThemeButton.classList.toggle("is-active", resolvedTheme === "grey");
  darkThemeButton.classList.toggle("is-active", resolvedTheme === "dark");
  greyThemeButton.setAttribute("aria-pressed", String(resolvedTheme === "grey"));
  darkThemeButton.setAttribute("aria-pressed", String(resolvedTheme === "dark"));
}

async function loadCatalog({ refresh = false } = {}) {
  const query = (searchInput.value || "").trim();
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }
  if (refresh) {
    params.set("refresh", "1");
  }

  setFeedback(refresh ? "Refreshing from Oracle docs..." : "Loading models...");
  try {
    const response = await fetch(`/api/models?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || "Request failed.");
    }
    renderCatalog(payload);
    const sourceTime = payload.generated_at ? `Updated ${payload.generated_at}` : "Loaded";
    const pageCount = payload.page_count ? ` Crawled ${payload.page_count} Oracle imported-model page(s).` : "";
    setFeedback(
      `${sourceTime}.${pageCount} Search supports wildcard patterns like qwen* and looser relative matches like llma -> llama.`,
    );
  } catch (error) {
    setFeedback(error.message || "Failed to load Oracle imported models.", true);
    results.innerHTML = '<div class="empty-state">The catalog could not be loaded. Check network access to Oracle docs and try refresh.</div>';
    familyCount.textContent = "-";
    modelCount.textContent = "-";
    generatedAt.textContent = "Unavailable";
  }
}

function setFeedback(message, isError = false) {
  feedback.textContent = message;
  feedback.classList.toggle("is-error", isError);
}

function renderCatalog(payload) {
  familyCount.textContent = String(payload.family_count ?? 0);
  modelCount.textContent = String(payload.model_count ?? 0);
  generatedAt.textContent = payload.generated_at
    ? `${payload.generated_at} from Oracle docs`
    : "No fetch timestamp";
  renderCrawledPages(payload.crawled_pages || []);

  results.innerHTML = "";
  if (!payload.families || payload.families.length === 0) {
    results.innerHTML =
      '<div class="empty-state">No matching models were found. Try a broader search like <code>vision</code>, <code>embed</code>, or <code>LLM</code>.</div>';
    return;
  }

  for (const family of payload.families) {
    const fragment = familyTemplate.content.cloneNode(true);
    fragment.querySelector(".family-name").textContent = family.name || family.page_title || "Model family";
    fragment.querySelector(".family-meta").textContent = `${family.page_title || family.name} • ${family.model_count || 0} model(s)`;
    fragment.querySelector(".family-model-count").textContent = `${family.model_count || 0} models`;

    const link = fragment.querySelector(".family-link");
    link.href = family.url;

    const errorNode = fragment.querySelector(".family-error");
    if (family.error) {
      errorNode.hidden = false;
      errorNode.textContent = `This family page could not be parsed: ${family.error}`;
    }

    const tbody = fragment.querySelector(".family-model-rows");
    if (!family.models || family.models.length === 0) {
      const row = document.createElement("tr");
      row.innerHTML = '<td colspan="4">No models were extracted from this page.</td>';
      tbody.appendChild(row);
    } else {
      for (const model of family.models) {
        const row = document.createElement("tr");
        const modelLink = model.huggingface_url
          ? `<div class="model-links"><a href="${escapeAttribute(model.huggingface_url)}" rel="noreferrer" target="_blank">Hugging Face</a></div>`
          : "";
        row.innerHTML = `
          <td>${escapeHtml(model.section || "")}</td>
          <td><code>${escapeHtml(model.model_id || "")}</code>${modelLink}</td>
          <td>${escapeHtml(model.capability || "")}</td>
          <td>${escapeHtml(model.recommended_shape || "")}</td>
        `;
        tbody.appendChild(row);
      }
    }
    results.appendChild(fragment);
  }
}

function renderCrawledPages(pages) {
  crawlPages.innerHTML = "";
  if (!pages.length) {
    crawlPages.innerHTML = '<p class="crawl-pages__empty">No subpages recorded for this fetch yet.</p>';
    return;
  }
  const list = document.createElement("ul");
  list.className = "crawl-pages__list";
  for (const page of pages) {
    const item = document.createElement("li");
    item.innerHTML = `<a href="${escapeAttribute(page.url || "#")}" rel="noreferrer" target="_blank">${escapeHtml(page.title || page.url || "Untitled page")}</a>`;
    list.appendChild(item);
  }
  crawlPages.appendChild(list);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return String(value).replaceAll('"', "&quot;");
}

greyThemeButton.addEventListener("click", () => applyTheme("grey"));
darkThemeButton.addEventListener("click", () => applyTheme("dark"));
searchButton.addEventListener("click", () => loadCatalog());
refreshButton.addEventListener("click", () => loadCatalog({ refresh: true }));
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    loadCatalog();
  }
});

applyTheme(window.localStorage.getItem(THEME_STORAGE_KEY) || "grey");
loadCatalog();
