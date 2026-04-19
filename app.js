const state = {
  materials: [],
  rebuyItems: [],
  locations: [],
  flies: [],
  bugReports: [],
  summary: {
    material_count: 0,
    location_count: 0,
    out_count: 0,
    fly_count: 0
  },
  activeTypeFilter: "",
  draftImageData: "",
  draftFlyImageData: "",
  cameraStream: null,
  currentPage: "atlas",
  installPrompt: null,
  auth: {
    configured: false,
    googleClientId: "",
    user: null
  }
};

const pageTitles = {
  atlas: "Bench Atlas",
  inventory: "Inventory",
  flies: "Flies & Recipes",
  rebuy: "Rebuy List",
  locations: "Storage Spots",
  bugs: "Bug Reports",
  account: "Account"
};

const elements = {
  pageTitle: document.querySelector("#page-title"),
  materialCount: document.querySelector("#material-count"),
  locationCount: document.querySelector("#location-count"),
  rebuyCount: document.querySelector("#rebuy-count"),
  dashboardTotalMaterials: document.querySelector("#dashboard-total-materials"),
  dashboardTotalLocations: document.querySelector("#dashboard-total-locations"),
  dashboardOutCount: document.querySelector("#dashboard-out-count"),
  dashboardFlyCount: document.querySelector("#dashboard-fly-count"),
  search: document.querySelector("#search-input"),
  categoryFilter: document.querySelector("#category-filter"),
  locationFilter: document.querySelector("#location-filter"),
  statusFilter: document.querySelector("#status-filter"),
  refreshButton: document.querySelector("#refresh-button"),
  statusMessage: document.querySelector("#status-message"),
  results: document.querySelector("#lookup-results"),
  rebuyList: document.querySelector("#rebuy-list"),
  dashboardRebuyList: document.querySelector("#dashboard-rebuy-list"),
  locationMap: document.querySelector("#location-map"),
  dashboardLocationMap: document.querySelector("#dashboard-location-map"),
  flyList: document.querySelector("#fly-list"),
  dashboardFlyList: document.querySelector("#dashboard-fly-list"),
  flyMaterialPicker: document.querySelector("#fly-material-picker"),
  bugReportList: document.querySelector("#bug-report-list"),
  mainShell: document.querySelector("#main-shell"),
  materialForm: document.querySelector("#material-form"),
  locationForm: document.querySelector("#location-form"),
  flyForm: document.querySelector("#fly-form"),
  bugReportForm: document.querySelector("#bug-report-form"),
  materialLocationSelect: document.querySelector("#material-location-select"),
  materialImageInput: document.querySelector("#material-image-input"),
  materialImagePreview: document.querySelector("#material-image-preview"),
  flyImageInput: document.querySelector("#fly-image-input"),
  flyImagePreview: document.querySelector("#fly-image-preview"),
  openCameraButton: document.querySelector("#open-camera-button"),
  clearImageButton: document.querySelector("#clear-image-button"),
  cameraCapture: document.querySelector("#camera-capture"),
  cameraVideo: document.querySelector("#camera-video"),
  capturePhotoButton: document.querySelector("#capture-photo-button"),
  cancelCameraButton: document.querySelector("#cancel-camera-button"),
  locationTypeInput: document.querySelector("#location-type-input"),
  locationTypeGroup: document.querySelector("#location-type-group"),
  typeFilterGroup: document.querySelector("#type-filter-group"),
  navLinks: Array.from(document.querySelectorAll("[data-page-target]")),
  pages: Array.from(document.querySelectorAll("[data-page]")),
  accountName: document.querySelector("#account-name"),
  accountEmail: document.querySelector("#account-email"),
  accountPageName: document.querySelector("#account-page-name"),
  accountPageEmail: document.querySelector("#account-page-email"),
  accountPageStatus: document.querySelector("#account-page-status"),
  authMessage: document.querySelector("#auth-message"),
  authConfigMessage: document.querySelector("#auth-config-message"),
  logoutButton: document.querySelector("#logout-button"),
  accountPageLogoutButton: document.querySelector("#account-page-logout-button"),
  googleAuthSlot: document.querySelector("#google-auth-slot"),
  accountPageAuthSlot: document.querySelector("#account-page-auth-slot"),
  installAppButton: document.querySelector("#install-app-button"),
  installStatus: document.querySelector("#install-status"),
  template: document.querySelector("#material-card-template"),
  rebuyTemplate: document.querySelector("#rebuy-item-template"),
  flyTemplate: document.querySelector("#fly-card-template"),
  bugReportTemplate: document.querySelector("#bug-report-template")
};

initialize().catch((error) => {
  setStatus(error.message || "The app could not finish loading.", "error");
});

async function initialize() {
  attachEvents();
  registerServiceWorker();
  updateSegmentedState(elements.typeFilterGroup, "[data-type-filter]", state.activeTypeFilter);
  updateSegmentedState(elements.locationTypeGroup, "[data-location-type]", elements.locationTypeInput.value);
  syncLocationNamePlaceholder(elements.locationTypeInput.value);
  renderImagePreview("");
  renderFlyImagePreview("");
  updateInstallState();
  syncPageFromHash();
  await loadAuthConfig();
  await refreshData();
}

function attachEvents() {
  window.addEventListener("hashchange", syncPageFromHash);
  window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
  window.addEventListener("appinstalled", handleAppInstalled);

  elements.navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      const target = link.dataset.pageTarget;
      if (target) {
        window.location.hash = target;
      }
    });
  });

  elements.refreshButton.addEventListener("click", refreshData);
  elements.search.addEventListener("input", refreshData);
  elements.categoryFilter.addEventListener("change", refreshData);
  elements.locationFilter.addEventListener("change", refreshData);
  elements.statusFilter.addEventListener("change", refreshData);

  elements.typeFilterGroup.addEventListener("click", (event) => {
    const button = event.target.closest("[data-type-filter]");
    if (!button) {
      return;
    }

    state.activeTypeFilter = button.dataset.typeFilter || "";
    updateSegmentedState(elements.typeFilterGroup, "[data-type-filter]", state.activeTypeFilter);
    refreshData();
  });

  elements.locationTypeGroup.addEventListener("click", (event) => {
    const button = event.target.closest("[data-location-type]");
    if (!button) {
      return;
    }

    const nextType = button.dataset.locationType || "Drawer";
    elements.locationTypeInput.value = nextType;
    updateSegmentedState(elements.locationTypeGroup, "[data-location-type]", nextType);
    syncLocationNamePlaceholder(nextType);
  });

  elements.materialImageInput.addEventListener("change", async (event) => {
    const [file] = event.currentTarget.files || [];
    if (!file) {
      state.draftImageData = "";
      renderImagePreview("");
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      state.draftImageData = dataUrl;
      stopCameraStream();
      renderImagePreview(dataUrl, file.name);
    } catch {
      setStatus("That picture could not be loaded.", "error");
      event.currentTarget.value = "";
      state.draftImageData = "";
      renderImagePreview("");
    }
  });

  elements.flyImageInput.addEventListener("change", async (event) => {
    const [file] = event.currentTarget.files || [];
    if (!file) {
      state.draftFlyImageData = "";
      renderFlyImagePreview("");
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      state.draftFlyImageData = dataUrl;
      renderFlyImagePreview(dataUrl, file.name);
    } catch {
      setStatus("That fly photo could not be loaded.", "error");
      event.currentTarget.value = "";
      state.draftFlyImageData = "";
      renderFlyImagePreview("");
    }
  });

  elements.openCameraButton.addEventListener("click", openCameraCapture);
  elements.capturePhotoButton.addEventListener("click", capturePhotoFromCamera);
  elements.cancelCameraButton.addEventListener("click", () => {
    stopCameraStream();
    setCameraOpen(false);
  });
  elements.clearImageButton.addEventListener("click", clearDraftImage);

  elements.logoutButton.addEventListener("click", logout);
  elements.accountPageLogoutButton.addEventListener("click", logout);
  elements.installAppButton.addEventListener("click", installApp);

  elements.materialForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload = formToJson(formData);

    try {
      payload.quantity = Number(payload.quantity || 0);
      delete payload.image_file;
      if (state.draftImageData) {
        payload.image_data = state.draftImageData;
      }

      setStatus("Saving material...");
      await fetchJson("/api/materials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      event.currentTarget.reset();
      clearDraftImage();
      setStatus("Material saved.", "success");
      await refreshData();
    } catch (error) {
      setStatus(error.message, "error");
    }
  });

  elements.locationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToJson(new FormData(event.currentTarget));

    try {
      setStatus("Saving location...");
      await fetchJson("/api/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      event.currentTarget.reset();
      elements.locationTypeInput.value = "Drawer";
      updateSegmentedState(elements.locationTypeGroup, "[data-location-type]", "Drawer");
      syncLocationNamePlaceholder("Drawer");
      setStatus("Location saved.", "success");
      await refreshData();
    } catch (error) {
      setStatus(error.message, "error");
    }
  });

  elements.flyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload = formToJson(formData);

    payload.material_ids = getSelectedFlyMaterialIds();
    delete payload.image_file;
    if (state.draftFlyImageData) {
      payload.image_data = state.draftFlyImageData;
    }

    try {
      setStatus("Saving fly recipe...");
      await fetchJson("/api/flies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      event.currentTarget.reset();
      state.draftFlyImageData = "";
      renderFlyImagePreview("");
      renderFlyMaterialPicker();
      setStatus("Fly recipe saved.", "success");
      await refreshData();
      window.location.hash = "flies";
    } catch (error) {
      setStatus(error.message, "error");
    }
  });

  elements.bugReportForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToJson(new FormData(event.currentTarget));

    try {
      setStatus("Saving bug report...");
      await fetchJson("/api/bug-reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      event.currentTarget.reset();
      setStatus("Bug report saved.", "success");
      await refreshData();
      window.location.hash = "bugs";
    } catch (error) {
      setStatus(error.message, "error");
    }
  });
}

async function loadAuthConfig() {
  const config = await fetchJson("/api/config");
  state.auth.configured = Boolean(config.google_client_id);
  state.auth.googleClientId = config.google_client_id || "";
  state.auth.user = config.user || null;
  renderAuthState();
  initializeGoogleAuth();
}

function initializeGoogleAuth() {
  if (!state.auth.configured || !window.google?.accounts?.id) {
    return;
  }

  window.google.accounts.id.initialize({
    client_id: state.auth.googleClientId,
    callback: handleGoogleCredential
  });

  [elements.googleAuthSlot, elements.accountPageAuthSlot].forEach((slot) => {
    slot.innerHTML = "";
    window.google.accounts.id.renderButton(slot, {
      theme: "outline",
      size: "large",
      shape: "pill",
      width: 260
    });
  });
}

async function handleGoogleCredential(response) {
  try {
    setStatus("Signing in...");
    const payload = await fetchJson("/api/auth/google", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: response.credential })
    });
    state.auth.user = payload.user;
    renderAuthState();
    setStatus("Signed in successfully.", "success");
    await refreshData();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function logout() {
  try {
    setStatus("Signing out...");
    await fetchJson("/api/auth/logout", { method: "POST" });
    state.auth.user = null;
    renderAuthState();
    setStatus("Signed out.", "success");
    await refreshData();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderAuthState() {
  const user = state.auth.user;
  const isSignedIn = Boolean(user);
  const name = user?.name || "Guest";
  const email = user?.email || "Local device only";

  elements.accountName.textContent = name;
  elements.accountEmail.textContent = email;
  elements.accountPageName.textContent = name;
  elements.accountPageEmail.textContent = email;
  elements.accountPageStatus.textContent = isSignedIn ? "Google account connected" : "Guest mode";

  elements.logoutButton.classList.toggle("ghost-button--hidden", !isSignedIn);
  elements.accountPageLogoutButton.classList.toggle("ghost-button--hidden", !isSignedIn);

  if (state.auth.configured) {
    elements.authMessage.textContent = isSignedIn
      ? "Your inventory is tied to this Google account and can be reached on other signed-in devices."
      : "Sign in with Google to sync your materials list across devices.";
    elements.authConfigMessage.textContent = isSignedIn
      ? "This account is now the owner of the data you create in this session."
      : "Google sign-in is ready. Use it here to sync your list across devices.";
  } else {
    elements.authMessage.textContent = "Google sign-in is not configured yet, so the app is staying in guest mode.";
    elements.authConfigMessage.textContent = "To enable cross-device access, set a Google client ID in the server environment.";
  }
}

function syncPageFromHash() {
  const target = window.location.hash.replace("#", "") || "atlas";
  const nextPage = pageTitles[target] ? target : "atlas";
  state.currentPage = nextPage;
  elements.pageTitle.textContent = pageTitles[nextPage];
  elements.mainShell.classList.toggle("main-shell--atlas", nextPage === "atlas");

  elements.pages.forEach((page) => {
    page.classList.toggle("is-active", page.dataset.page === nextPage);
  });

  elements.navLinks.forEach((link) => {
    link.classList.toggle("is-active", link.dataset.pageTarget === nextPage);
  });
}

async function refreshData() {
  try {
    setStatus("Loading inventory...");
    const [materials, rebuyItems, locations, flies, bugReports, summary] = await Promise.all([
      loadMaterials(),
      fetchJson("/api/materials?status=out"),
      fetchJson("/api/locations"),
      fetchJson("/api/flies"),
      fetchJson("/api/bug-reports"),
      fetchJson("/api/summary")
    ]);

    state.materials = materials;
    state.rebuyItems = rebuyItems;
    state.locations = locations;
    state.flies = flies;
    state.bugReports = bugReports;
    state.summary = summary;

    updateStats();
    updateFilters();
    updateLocationSelect();
    renderMaterials();
    renderRebuyList(elements.rebuyList);
    renderRebuyList(elements.dashboardRebuyList, state.rebuyItems.slice(0, 3));
    renderLocations(elements.locationMap);
    renderLocations(elements.dashboardLocationMap, state.locations.slice(0, 4));
    renderFlyMaterialPicker();
    renderFlies(elements.flyList);
    renderFlies(elements.dashboardFlyList, state.flies.slice(0, 3), true);
    renderBugReports();
    setStatus(`Showing ${state.materials.length} material${state.materials.length === 1 ? "" : "s"}.`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function buildMaterialQuery() {
  const params = new URLSearchParams();
  const search = elements.search.value.trim();
  const category = elements.categoryFilter.value;
  const locationId = elements.locationFilter.value;

  if (search) {
    params.set("search", search);
  }
  if (category) {
    params.set("category", category);
  }
  if (locationId) {
    params.set("location_id", locationId);
  }
  if (elements.statusFilter.value) {
    params.set("status", elements.statusFilter.value);
  }
  if (state.activeTypeFilter) {
    params.set("location_type", state.activeTypeFilter);
  }

  const queryString = params.toString();
  return queryString ? `/api/materials?${queryString}` : "/api/materials";
}

function loadMaterials() {
  return fetchJson(buildMaterialQuery());
}

function updateStats() {
  elements.materialCount.textContent = String(state.summary.material_count);
  elements.locationCount.textContent = String(state.summary.location_count);
  elements.rebuyCount.textContent = String(state.summary.out_count || 0);
  elements.dashboardTotalMaterials.textContent = String(state.summary.material_count);
  elements.dashboardTotalLocations.textContent = String(state.summary.location_count);
  elements.dashboardOutCount.textContent = String(state.summary.out_count || 0);
  elements.dashboardFlyCount.textContent = String(state.summary.fly_count || 0);
}

function updateFilters() {
  const categoryValue = elements.categoryFilter.value;
  const locationValue = elements.locationFilter.value;

  const categories = [...new Set(state.materials.map((material) => material.category).filter(Boolean))].sort();
  const locationOptions = state.locations
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name));

  hydrateSelect(
    elements.categoryFilter,
    [{ value: "", label: "All categories" }, ...categories.map((category) => ({ value: category, label: category }))],
    categoryValue
  );

  hydrateSelect(
    elements.locationFilter,
    [{
      value: "",
      label: "All locations"
    }, ...locationOptions.map((location) => ({
      value: String(location.id),
      label: `${location.location_type ? `${location.location_type}: ` : ""}${location.name}`
    }))],
    locationValue
  );
}

function updateLocationSelect() {
  const selectedValue = elements.materialLocationSelect.value;
  const options = state.locations
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name))
    .map((location) => ({
      value: String(location.id),
      label: `${location.location_type ? `${location.location_type}: ` : ""}${location.name}${location.zone ? ` - ${location.zone}` : ""}`
    }));

  hydrateSelect(elements.materialLocationSelect, options, selectedValue);
}

function hydrateSelect(select, options, selectedValue) {
  select.innerHTML = "";

  options.forEach((option) => {
    const optionElement = document.createElement("option");
    optionElement.value = option.value;
    optionElement.textContent = option.label;
    if (option.value === selectedValue) {
      optionElement.selected = true;
    }
    select.appendChild(optionElement);
  });

  if (!select.value && options[0]) {
    select.value = options[0].value;
  }
}

function renderMaterials() {
  elements.results.innerHTML = "";

  if (!state.materials.length) {
    elements.results.appendChild(createEmptyState("No materials matched your search yet."));
    return;
  }

  state.materials.forEach((material) => {
    const fragment = elements.template.content.cloneNode(true);
    const typePill = fragment.querySelector(".location-type-pill");
    const statusValue = material.is_out ? "Need to rebuy" : "Available";
    const card = fragment.querySelector(".material-card");
    const toggleButton = fragment.querySelector(".toggle-status-button");
    const image = fragment.querySelector(".material-image");
    const imageWrap = fragment.querySelector(".material-image-wrap");

    fragment.querySelector(".material-name").textContent = material.name;
    fragment.querySelector(".material-meta").textContent = [
      material.category,
      material.brand,
      material.variant
    ].filter(Boolean).join(" - ");
    fragment.querySelector(".material-location").textContent = material.location_name
      ? `${material.location_type ? `${material.location_type}: ` : ""}${material.location_name}${material.location_zone ? ` (${material.location_zone})` : ""}`
      : "Location missing";
    fragment.querySelector(".material-quantity").textContent = String(material.quantity);
    fragment.querySelector(".material-status").textContent = statusValue;
    fragment.querySelector(".material-notes").textContent = material.notes || "No notes yet.";
    typePill.textContent = material.location_type || "Storage";
    card.classList.toggle("material-card--out", Boolean(material.is_out));
    toggleCardImage(image, imageWrap, material.image_data, material.name);
    toggleButton.textContent = material.is_out ? "Mark as restocked" : "Mark as run out";
    toggleButton.addEventListener("click", () => {
      toggleMaterialStatus(material);
    });

    elements.results.appendChild(fragment);
  });
}

function renderLocations(container, locations = state.locations) {
  container.innerHTML = "";

  if (!locations.length) {
    container.appendChild(createEmptyState("Add your first location to build your storage map."));
    return;
  }

  locations.forEach((location) => {
    const card = document.createElement("article");
    card.className = "location-card";
    card.innerHTML = `
      <h3>${escapeHtml(location.name)}</h3>
      <p><strong class="inline-type">${escapeHtml(location.location_type || "Storage")}</strong></p>
      <p>${escapeHtml(location.zone || "No zone assigned")}</p>
      <p>${escapeHtml(location.description || "No description yet.")}</p>
      <strong>${location.material_count} material${location.material_count === 1 ? "" : "s"} stored here</strong>
    `;
    container.appendChild(card);
  });
}

function renderRebuyList(container, items = state.rebuyItems) {
  container.innerHTML = "";

  if (!items.length) {
    container.appendChild(createEmptyState("No run-out materials right now."));
    return;
  }

  items.forEach((material) => {
    const fragment = elements.rebuyTemplate.content.cloneNode(true);
    const image = fragment.querySelector(".rebuy-image");
    const imageWrap = fragment.querySelector(".rebuy-image-wrap");

    fragment.querySelector(".rebuy-item__name").textContent = material.name;
    fragment.querySelector(".rebuy-item__meta").textContent = [
      material.category,
      material.brand,
      material.variant
    ].filter(Boolean).join(" - ");
    fragment.querySelector(".rebuy-item__location").textContent = material.location_name
      ? `Last stored in ${material.location_type ? `${material.location_type}: ` : ""}${material.location_name}${material.location_zone ? ` (${material.location_zone})` : ""}`
      : "No storage location recorded.";
    toggleCardImage(image, imageWrap, material.image_data, material.name);
    fragment.querySelector(".rebuy-item__action").addEventListener("click", () => {
      toggleMaterialStatus(material);
    });

    container.appendChild(fragment);
  });
}

function renderFlyMaterialPicker() {
  elements.flyMaterialPicker.innerHTML = "";

  if (!state.materials.length) {
    elements.flyMaterialPicker.appendChild(createEmptyState("Add materials first so you can build a fly recipe."));
    return;
  }

  state.materials.forEach((material) => {
    const label = document.createElement("label");
    label.className = "material-pick";
    const statusText = material.is_out ? "Need to rebuy" : "Ready";
    label.innerHTML = `
      <input type="checkbox" value="${material.id}">
      <div>
        <strong>${escapeHtml(material.name)}</strong>
        <span>${escapeHtml([
          material.category,
          material.variant,
          material.location_type ? `${material.location_type}: ${material.location_name}` : material.location_name,
          statusText
        ].filter(Boolean).join(" - "))}</span>
      </div>
    `;
    elements.flyMaterialPicker.appendChild(label);
  });
}

function getSelectedFlyMaterialIds() {
  return Array.from(elements.flyMaterialPicker.querySelectorAll("input:checked"))
    .map((input) => Number(input.value))
    .filter((value) => Number.isInteger(value));
}

function renderFlies(container, flies = state.flies, compact = false) {
  container.innerHTML = "";

  if (!flies.length) {
    container.appendChild(createEmptyState("No fly recipes saved yet."));
    return;
  }

  flies.forEach((fly) => {
    const fragment = elements.flyTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".fly-card");
    const image = fragment.querySelector(".fly-image");
    const imageWrap = fragment.querySelector(".fly-image-wrap");
    const materialsWrap = fragment.querySelector(".fly-materials");

    fragment.querySelector(".fly-name").textContent = fly.name;
    fragment.querySelector(".fly-meta").textContent = [fly.style, fly.hook_size].filter(Boolean).join(" - ") || "Pattern details";
    fragment.querySelector(".fly-recipe").textContent = fly.recipe || "No tying notes yet.";
    toggleCardImage(image, imageWrap, fly.image_data, fly.name);
    card.classList.toggle("fly-card--compact", compact);

    if (!fly.materials.length) {
      materialsWrap.appendChild(createInlineState("No materials linked yet."));
    } else {
      fly.materials.forEach((material) => {
        const chip = document.createElement("div");
        chip.className = "fly-material-chip";
        chip.classList.toggle("is-out", Boolean(material.is_out));
        chip.innerHTML = `
          <strong>${escapeHtml(material.name)}</strong>
          <span>${escapeHtml([
            material.location_type ? `${material.location_type}: ${material.location_name}` : material.location_name,
            material.location_zone ? `(${material.location_zone})` : "",
            material.is_out ? "Need to rebuy" : "Ready"
          ].filter(Boolean).join(" "))}</span>
        `;
        materialsWrap.appendChild(chip);
      });
    }

    container.appendChild(fragment);
  });
}

function renderBugReports() {
  elements.bugReportList.innerHTML = "";

  if (!state.bugReports.length) {
    elements.bugReportList.appendChild(createEmptyState("No bug reports have been logged yet."));
    return;
  }

  state.bugReports.forEach((report) => {
    const fragment = elements.bugReportTemplate.content.cloneNode(true);
    const severity = report.severity || "Medium";
    const severityClassName = `bug-report-severity bug-report-severity--${severity.toLowerCase()}`;

    fragment.querySelector(".bug-report-title").textContent = report.title;
    fragment.querySelector(".bug-report-meta").textContent = [
      report.page || "Unassigned page",
      report.status || "Open"
    ].filter(Boolean).join(" - ");
    fragment.querySelector(".bug-report-severity").textContent = severity;
    fragment.querySelector(".bug-report-severity").className = severityClassName;
    fragment.querySelector(".bug-report-details").textContent = report.details || "No details provided.";
    fragment.querySelector(".bug-report-footer").textContent = `Reported ${formatDateTime(report.created_at)}`;

    elements.bugReportList.appendChild(fragment);
  });
}

function createEmptyState(message) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = message;
  return element;
}

function createInlineState(message) {
  const element = document.createElement("div");
  element.className = "inline-state";
  element.textContent = message;
  return element;
}

function setStatus(message, tone = "") {
  elements.statusMessage.textContent = message;
  elements.statusMessage.className = "status-message";
  if (tone) {
    elements.statusMessage.classList.add(tone);
  }
}

function renderImagePreview(dataUrl, fileName = "") {
  renderPreview(elements.materialImagePreview, dataUrl, fileName, "No picture selected yet.");
}

function renderFlyImagePreview(dataUrl, fileName = "") {
  renderPreview(elements.flyImagePreview, dataUrl, fileName, "No fly photo selected yet.");
}

function renderPreview(container, dataUrl, fileName, emptyMessage) {
  container.innerHTML = "";
  container.classList.toggle("image-preview--empty", !dataUrl);

  if (!dataUrl) {
    const paragraph = document.createElement("p");
    paragraph.textContent = emptyMessage;
    container.appendChild(paragraph);
    return;
  }

  const image = document.createElement("img");
  image.src = dataUrl;
  image.alt = fileName ? `${fileName} preview` : "Preview";
  container.appendChild(image);
}

function clearDraftImage() {
  elements.materialImageInput.value = "";
  state.draftImageData = "";
  stopCameraStream();
  setCameraOpen(false);
  renderImagePreview("");
}

async function openCameraCapture() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus("Camera capture is not available here. You can still use the picture picker.", "error");
    return;
  }

  try {
    stopCameraStream();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" }
      },
      audio: false
    });
    state.cameraStream = stream;
    elements.cameraVideo.srcObject = stream;
    setCameraOpen(true);
    setStatus("Camera ready. Capture a photo when you're set.");
  } catch {
    setStatus("Camera access was not allowed. You can still use the picture picker.", "error");
    stopCameraStream();
    setCameraOpen(false);
  }
}

function capturePhotoFromCamera() {
  if (!state.cameraStream) {
    setStatus("Open the camera first to take a picture.", "error");
    return;
  }

  const width = elements.cameraVideo.videoWidth;
  const height = elements.cameraVideo.videoHeight;
  if (!width || !height) {
    setStatus("The camera preview is still loading. Try again in a moment.", "error");
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    setStatus("The photo could not be captured on this device.", "error");
    return;
  }

  context.drawImage(elements.cameraVideo, 0, 0, width, height);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
  state.draftImageData = dataUrl;
  elements.materialImageInput.value = "";
  renderImagePreview(dataUrl, "Captured photo");
  stopCameraStream();
  setCameraOpen(false);
  setStatus("Picture captured.", "success");
}

function stopCameraStream() {
  if (state.cameraStream) {
    state.cameraStream.getTracks().forEach((track) => track.stop());
    state.cameraStream = null;
  }
  if (elements.cameraVideo.srcObject) {
    elements.cameraVideo.srcObject = null;
  }
}

function setCameraOpen(isOpen) {
  elements.cameraCapture.classList.toggle("camera-capture--hidden", !isOpen);
}

function toggleCardImage(image, imageWrap, dataUrl, name) {
  const hasImage = Boolean(dataUrl);
  imageWrap.classList.toggle("is-empty", !hasImage);
  image.hidden = !hasImage;
  if (hasImage) {
    image.src = dataUrl;
    image.alt = `${name} photo`;
  } else {
    image.removeAttribute("src");
    image.alt = "";
  }
}

async function toggleMaterialStatus(material) {
  const nextState = !material.is_out;
  const statusLabel = nextState ? "run out" : "restocked";

  try {
    setStatus(`Marking ${material.name} as ${statusLabel}...`);
    await fetchJson(`/api/materials/${material.id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_out: nextState })
    });
    setStatus(`${material.name} updated.`, "success");
    await refreshData();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function updateSegmentedState(container, selector, activeValue) {
  container.querySelectorAll(selector).forEach((button) => {
    const buttonValue = button.dataset.typeFilter ?? button.dataset.locationType ?? "";
    button.classList.toggle("is-active", buttonValue === activeValue);
  });
}

function syncLocationNamePlaceholder(locationType) {
  const input = elements.locationForm.querySelector('input[name="name"]');
  const placeholderByType = {
    Drawer: "Drawer A2",
    Bin: "Bin 3",
    "Travel Kit": "Travel Kit"
  };
  input.placeholder = placeholderByType[locationType] || "Storage location";
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch {
    // PWA support is helpful but should never block the inventory app.
  }
}

function handleBeforeInstallPrompt(event) {
  event.preventDefault();
  state.installPrompt = event;
  updateInstallState();
}

function handleAppInstalled() {
  state.installPrompt = null;
  updateInstallState("Bench Atlas is installed on this device.");
}

async function installApp() {
  if (!state.installPrompt) {
    updateInstallState("Open this live site in Chrome on Android and use Add to Home screen.");
    return;
  }

  try {
    await state.installPrompt.prompt();
    await state.installPrompt.userChoice;
  } finally {
    state.installPrompt = null;
    updateInstallState();
  }
}

function updateInstallState(message = "") {
  const isStandalone = window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone;
  const canInstall = Boolean(state.installPrompt) && !isStandalone;

  elements.installAppButton.classList.toggle("install-button--hidden", !canInstall);

  if (message) {
    elements.installStatus.textContent = message;
    return;
  }

  if (isStandalone) {
    elements.installStatus.textContent = "Bench Atlas is already installed and can be opened from your home screen.";
    return;
  }

  if (canInstall) {
    elements.installStatus.textContent = "Bench Atlas is ready to install on this device.";
    return;
  }

  elements.installStatus.textContent = "If the install button is not available yet, open the live site in Chrome on Android and use Add to Home screen.";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options
  });
  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(payload.error || "The request could not be completed.");
  }

  return payload;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("File read failed."));
    reader.readAsDataURL(file);
  });
}

function formToJson(formData) {
  const payload = {};
  for (const [key, value] of formData.entries()) {
    payload[key] = String(value).trim();
  }
  return payload;
}

function formatDateTime(value) {
  if (!value) {
    return "just now";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(parsed);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
