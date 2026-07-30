// YouTube Curator — Main Application Entry (ES Module)

let csrfToken = null;
let activeFormKeywords = []; // Array temporal para las keywords en el formulario
let currentCategories = []; // Array con el listado actual de categorías cargadas

// Variables de estado de paginación y filtros para canales y videos
let channelsNextCursor = null;
let channelsSearchTimeout = null;

let videosNextCursor = null;
let videosSearchTimeout = null;

document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

function initApp() {
    console.log("YouTube Curator inicializado...");
    
    // Configurar menú móvil
    setupMobileMenu();
    
    // Configurar enrutador y clicks SPA (Fase 3/5)
    setupSPARouting();
    
    // Verificar estado de autenticación inicial
    checkAuthStatus();
    
    // Configurar manejador del botón de actualización
    setupRefreshButton();

    // Configurar administrador de categorías (Fase 2)
    setupCategoryManager();

    // Configurar clasificador manual de canales (Fase 4)
    setupChannelClassifier();
}

function setupMobileMenu() {
    const menuToggle = document.getElementById("menu-toggle");
    const sidebar = document.getElementById("sidebar");
    
    if (menuToggle && sidebar) {
        menuToggle.addEventListener("click", () => {
            sidebar.classList.toggle("open");
            const isOpen = sidebar.classList.contains("open");
            menuToggle.setAttribute("aria-expanded", isOpen);
        });
        
        // Cerrar al hacer click fuera del sidebar en móvil
        document.addEventListener("click", (e) => {
            if (window.innerWidth <= 768) {
                if (!sidebar.contains(e.target) && !menuToggle.contains(e.target) && sidebar.classList.contains("open")) {
                    sidebar.classList.remove("open");
                    menuToggle.setAttribute("aria-expanded", "false");
                }
            }
        });
    }
}

// Wrapper seguro para fetch que inyecta automáticamente el token CSRF para mutaciones
export async function apiFetch(url, options = {}) {
    if (!options.headers) {
        options.headers = {};
    }
    
    const method = (options.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && csrfToken) {
        options.headers["X-CSRF-Token"] = csrfToken;
    }
    
    // Configurar cabeceras por defecto si es JSON
    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
        options.body = JSON.stringify(options.body);
        options.headers["Content-Type"] = "application/json";
    }
    
    const response = await fetch(url, options);
    
    // Redirigir a login si la API retorna 401
    if (response.status === 401) {
        csrfToken = null;
        showLoginScreen(true);
    }
    
    return response;
}

async function checkAuthStatus() {
    try {
        const response = await fetch("/api/v1/auth/status");
        if (response.ok) {
            const data = await response.json();
            if (data.authenticated) {
                csrfToken = data.csrfToken;
                showAppShell(data.email);
                
                // Cargar categorías primero para tenerlas cacheadas en la UI
                await loadCategories();
                
                // Procesar la ruta actual después de la autenticación
                handleCurrentRoute();
            } else {
                csrfToken = null;
                showLoginScreen();
            }
        } else {
            showLoginScreen();
        }
    } catch (error) {
        console.error("Error al obtener estado de autenticación:", error);
        showLoginScreen();
        const loginErrorEl = document.getElementById("login-error");
        if (loginErrorEl) {
            loginErrorEl.textContent = "Error de conexión con el servidor.";
            loginErrorEl.classList.remove("hidden");
        }
    }
}

function showAppShell(email) {
    const appShell = document.getElementById("app-shell");
    const loginScreen = document.getElementById("login-screen");
    const userEmailEl = document.getElementById("user-email");
    const userInfoEl = userEmailEl ? userEmailEl.parentElement : null;
    
    if (appShell) appShell.classList.remove("hidden");
    if (loginScreen) loginScreen.classList.add("hidden");
    
    if (userEmailEl) userEmailEl.textContent = email || "Conectado";
    if (userInfoEl) userInfoEl.classList.add("online");
}

function showLoginScreen(sessionExpired = false) {
    const appShell = document.getElementById("app-shell");
    const loginScreen = document.getElementById("login-screen");
    const loginErrorEl = document.getElementById("login-error");
    
    if (appShell) appShell.classList.add("hidden");
    if (loginScreen) loginScreen.classList.remove("hidden");
    
    // Comprobar si hay errores en los parámetros de la URL (OAuth callback errors)
    const urlParams = new URLSearchParams(window.location.search);
    const authError = urlParams.get("error");
    
    if (loginErrorEl) {
        if (sessionExpired) {
            loginErrorEl.textContent = "Tu sesión ha expirado. Por favor conéctate de nuevo.";
            loginErrorEl.classList.remove("hidden");
        } else if (authError) {
            loginErrorEl.textContent = decodeURIComponent(authError);
            loginErrorEl.classList.remove("hidden");
            // Limpiar query params de la URL sin recargar la página
            window.history.replaceState({}, document.title, "/");
        } else {
            loginErrorEl.classList.add("hidden");
        }
    }
}

async function loadCategories() {
    const categoriesList = document.getElementById("sidebar-categories");
    if (!categoriesList) return;
    
    try {
        const response = await apiFetch("/api/v1/categories");
        if (response.ok) {
            const data = await response.json();
            currentCategories = data.items || [];
            categoriesList.innerHTML = "";
            
            if (currentCategories.length === 0) {
                categoriesList.innerHTML = '<div class="loading-placeholder-nav">Sin categorías</div>';
                return;
            }
            
            currentCategories.forEach(category => {
                const item = document.createElement("a");
                item.href = `/category/${category.id}`;
                item.className = "nav-item";
                item.setAttribute("data-category-id", category.id);
                item.innerHTML = `
                    <span class="nav-icon">📁</span>
                    <span class="nav-label">${escapeHtml(category.name)}</span>
                `;
                
                // Interceptar click para navegación SPA (Fase 2)
                item.addEventListener("click", (e) => {
                    e.preventDefault();
                    selectCategoryInSidebar(category.id);
                });
                
                categoriesList.appendChild(item);
            });
        } else {
            categoriesList.innerHTML = '<div class="loading-placeholder-nav">Error al cargar</div>';
        }
    } catch (error) {
        console.error("Error cargando categorías:", error);
        categoriesList.innerHTML = '<div class="loading-placeholder-nav">Error de conexión</div>';
    }
}

function selectCategoryInSidebar(categoryId) {
    // Navegar de forma SPA usando la nueva ruta path-based
    navigateToRoute(`/category/${categoryId}`);
}

/* --- Enrutador SPA de Navegación (Fase 3/5) --- */

function setupSPARouting() {
    // Interceptar todos los clicks de enlaces locales para navegación SPA
    document.addEventListener("click", (e) => {
        const link = e.target.closest("a");
        if (link && link.href) {
            const url = new URL(link.href);
            // Solo interceptar si es el mismo origen y no es una llamada a la API o logout
            if (url.origin === window.location.origin && 
                !url.pathname.startsWith("/api/") && 
                url.pathname !== "/auth/logout") {
                e.preventDefault();
                navigateToRoute(url.pathname + url.search);
            }
        }
    });

    // Escuchar el evento popstate para cuando el usuario retroceda/avance en el historial del navegador
    window.addEventListener("popstate", () => {
        handleCurrentRoute();
    });
}

function navigateToRoute(route) {
    window.history.pushState({}, "", route);
    handleCurrentRoute();
}

function handleCurrentRoute() {
    const path = window.location.pathname;
    
    // Resetear menú activo
    document.querySelectorAll(".sidebar-nav .nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll("#nav-settings, #nav-discoveries").forEach(el => el.classList.remove("active"));

    // Comprobar si coincide con /category/<id>
    const catMatch = path.match(/^\/category\/(\d+)/);

    if (catMatch) {
        const categoryId = parseInt(catMatch[1]);
        
        // Activar nav item correspondiente en sidebar
        const activeItem = document.querySelector(`.sidebar-nav .nav-item[data-category-id="${categoryId}"]`);
        if (activeItem) activeItem.classList.add("active");
        
        renderCategoryFeedView(categoryId);
    } else if (path === "/channels") {
        const navChannels = document.getElementById("nav-channels");
        if (navChannels) navChannels.classList.add("active");
        renderChannelsView();
    } else if (path === "/settings") {
        const navSettings = document.getElementById("nav-settings");
        if (navSettings) navSettings.classList.add("active");
        renderSettingsView();
    } else if (path === "/discoveries") {
        const navDiscoveries = document.getElementById("nav-discoveries");
        if (navDiscoveries) navDiscoveries.classList.add("active");
        renderDiscoveriesView();
    } else if (path === "/") {
        const navHome = document.getElementById("nav-home");
        if (navHome) navHome.classList.add("active");
        renderHomeView();
    }
}

function renderHomeView() {
    renderCategoryFeedView(null);
}

function renderSettingsView() {
    const viewContainer = document.getElementById("view-container");
    if (!viewContainer) return;

    const email = document.getElementById("user-email")?.textContent || "Conectado";

    viewContainer.innerHTML = `
        <div class="channels-view">
            <div class="channels-header">
                <h2 class="channels-title">Ajustes</h2>
            </div>
            
            <div class="category-toolbar" style="margin-bottom: 20px;">
                <p class="category-desc">Gestiona la conexión de tu cuenta y los diagnósticos del sistema.</p>
            </div>
            
            <div class="channels-grid" style="display: flex; flex-direction: column; gap: 20px;">
                <div class="channel-card" style="width: 100%; box-sizing: border-box; padding: 20px;">
                    <h3 style="margin-top: 0; color: #fff; font-size: 1.25rem;">Conexión Google OAuth 2.0</h3>
                    <p class="form-instruction" style="margin-bottom: 15px;">Sesión activa con el correo de propietario:</p>
                    <div style="font-weight: bold; margin-bottom: 20px; color: #a78bfa;">${escapeHtml(email)}</div>
                    
                    <div style="display: flex; gap: 10px;">
                        <button id="btn-settings-sync" class="btn-primary">🔄 Sincronizar Biblioteca</button>
                        <button id="btn-settings-logout" class="btn-secondary" style="border-color: #ef4444; color: #ef4444;">Cerrar Sesión</button>
                    </div>
                </div>
                
                <div class="channel-card" style="width: 100%; box-sizing: border-box; padding: 20px;">
                    <h3 style="margin-top: 0; color: #fff; font-size: 1.25rem;">Diagnóstico del Sistema</h3>
                    <p class="form-instruction">Estado actual de la base de datos y worker de sincronización.</p>
                    
                    <ul style="list-style: none; padding: 0; margin: 15px 0 0 0; display: flex; flex-direction: column; gap: 10px;">
                        <li style="display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px;">
                            <span>Base de datos SQLite:</span>
                            <span style="color: #10b981; font-weight: bold;">🟢 Activo (WAL enabled)</span>
                        </li>
                        <li style="display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px;">
                            <span>Protección CSRF:</span>
                            <span style="color: #10b981; font-weight: bold;">🟢 Activo (X-CSRF-Token)</span>
                        </li>
                        <li style="display: flex; justify-content: space-between;">
                            <span>Worker Daemon:</span>
                            <span style="color: #a78bfa;">Disponible en segundo plano</span>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    `;

    document.getElementById("btn-settings-sync")?.addEventListener("click", () => {
        triggerSubscriptionSync();
    });

    document.getElementById("btn-settings-logout")?.addEventListener("click", async () => {
        const confirmed = await showConfirmDialog("Cerrar Sesión", "¿Estás seguro de que deseas cerrar sesión?");
        if (confirmed) {
            try {
                const resp = await apiFetch("/api/v1/auth/logout", { method: "POST" });
                if (resp.status === 204) {
                    window.location.reload();
                }
            } catch (err) {
                console.error("Error al cerrar sesión:", err);
            }
        }
    });
}

function renderDiscoveriesView() {
    const viewContainer = document.getElementById("view-container");
    if (!viewContainer) return;

    viewContainer.innerHTML = `
        <div class="channels-view">
            <div class="channels-header">
                <h2 class="channels-title">Descubrimiento</h2>
            </div>
            
            <div class="category-toolbar" style="margin-bottom: 20px;">
                <p class="category-desc">Encuentra contenido recomendado según tus preferencias de filtrado y categorías.</p>
            </div>
            
            <div style="background: rgba(167, 139, 250, 0.05); border: 1px dashed rgba(167, 139, 250, 0.3); border-radius: 12px; padding: 40px 20px; text-align: center; max-width: 600px; margin: 40px auto;">
                <div style="font-size: 3rem; margin-bottom: 15px;">✨</div>
                <h3 style="color: #fff; margin-top: 0; font-size: 1.25rem;">Clasificación y sugerencias automáticas</h3>
                <p class="form-instruction" style="line-height: 1.6; margin-bottom: 0;">
                    El motor de descubrimiento y sugerencias con IA está planeado para la siguiente etapa de desarrollo (Fase 8). 
                    Las palabras clave configuradas en tus categorías y los canales que marques como seguidos serán utilizados 
                    para evaluar y traerte videos coincidentes recomendados.
                </p>
            </div>
        </div>
    `;
}

/* --- Vista de Feed de Categorías (Fase 5) --- */

async function renderCategoryFeedView(categoryId) {
    const viewContainer = document.getElementById("view-container");
    if (!viewContainer) return;

    // Obtener detalles de la categoría desde caché local o de API
    let category = null;
    if (categoryId) {
        category = currentCategories.find(c => c.id === categoryId);
        if (!category) {
            try {
                const resp = await apiFetch(`/api/v1/categories/${categoryId}`);
                if (resp.ok) {
                    category = await resp.json();
                }
            } catch (err) {
                console.error("Error al obtener categoría actual:", err);
            }
        }
    }

    const categoryName = category ? category.name : "Todos los Feeds";
    const categoryDesc = category ? (category.description || "Sin descripción") : "Feed unificado de todos tus canales seguidos y descubrimientos.";

    // Leer filtros iniciales desde la URL (query string)
    const urlParams = new URLSearchParams(window.location.search);
    const initialView = urlParams.get("view") || "feed";
    const initialWatched = urlParams.get("watched") || "false"; // Por defecto no vistos para priorizar pendientes
    const initialOrigin = urlParams.get("origin") || "all";
    const initialQuery = urlParams.get("query") || "";

    viewContainer.innerHTML = `
        <div class="category-view">
            <div class="category-header">
                <div class="category-title-area">
                    <h2 class="category-title">${escapeHtml(categoryName)}</h2>
                    <p class="category-desc">${escapeHtml(categoryDesc)}</p>
                </div>
                <div class="view-toggle-buttons">
                    <button id="btn-view-feed" class="btn-toggle ${initialView === "feed" ? "active" : ""}">Feed</button>
                    <button id="btn-view-channels" class="btn-toggle ${initialView === "channels" ? "active" : ""}">Por canal</button>
                </div>
            </div>
            
            <div class="category-toolbar">
                <div class="toolbar-search">
                    <span class="search-icon-inside">🔍</span>
                    <input type="text" id="video-search-input" placeholder="Buscar videos..." value="${escapeHtml(initialQuery)}">
                </div>
                <div class="toolbar-filters">
                    <select id="select-filter-watched" class="select-filter">
                        <option value="all" ${initialWatched === "all" ? "selected" : ""}>Todos los videos</option>
                        <option value="false" ${initialWatched === "false" ? "selected" : ""}>No vistos</option>
                        <option value="true" ${initialWatched === "true" ? "selected" : ""}>Vistos</option>
                    </select>
                    
                    <select id="select-filter-origin" class="select-filter">
                        <option value="all" ${initialOrigin === "all" ? "selected" : ""}>Procedencia: Todas</option>
                        <option value="followed" ${initialOrigin === "followed" ? "selected" : ""}>Solo mis canales</option>
                        <option value="discovery" ${initialOrigin === "discovery" ? "selected" : ""}>Solo descubrimientos</option>
                    </select>
                </div>
            </div>
            
            <div id="videos-container" class="videos-container">
                <!-- Se cargará la grilla de feed o lista agrupada por canal -->
            </div>
            
            <div id="videos-pagination" class="pagination-container hidden">
                <button id="btn-videos-load-more" class="btn-secondary">Cargar más</button>
            </div>
        </div>
    `;

    // Adjuntar listeners de filtros
    const btnFeed = document.getElementById("btn-view-feed");
    const btnChannels = document.getElementById("btn-view-channels");
    const selectWatched = document.getElementById("select-filter-watched");
    const selectOrigin = document.getElementById("select-filter-origin");
    const searchInput = document.getElementById("video-search-input");
    const btnLoadMore = document.getElementById("btn-videos-load-more");

    const updateFiltersAndReload = () => {
        const view = btnFeed.classList.contains("active") ? "feed" : "channels";
        const watched = selectWatched.value;
        const origin = selectOrigin.value;
        const query = searchInput.value.trim();

        // Actualizar URL sin recargar
        const url = new URL(window.location.href);
        url.searchParams.set("view", view);
        url.searchParams.set("watched", watched);
        url.searchParams.set("origin", origin);
        if (query) {
            url.searchParams.set("query", query);
        } else {
            url.searchParams.delete("query");
        }
        window.history.replaceState({}, "", url.toString());

        loadCategoryVideos(categoryId, true);
    };

    btnFeed.addEventListener("click", () => {
        btnFeed.classList.add("active");
        btnChannels.classList.remove("active");
        updateFiltersAndReload();
    });

    btnChannels.addEventListener("click", () => {
        btnChannels.classList.add("active");
        btnFeed.classList.remove("active");
        updateFiltersAndReload();
    });

    selectWatched.addEventListener("change", updateFiltersAndReload);
    selectOrigin.addEventListener("change", updateFiltersAndReload);

    searchInput.addEventListener("input", () => {
        clearTimeout(videosSearchTimeout);
        videosSearchTimeout = setTimeout(() => {
            updateFiltersAndReload();
        }, 300);
    });

    btnLoadMore.addEventListener("click", () => {
        if (videosNextCursor) {
            loadCategoryVideos(categoryId, false, videosNextCursor);
        }
    });

    // Cargar videos iniciales
    loadCategoryVideos(categoryId, true);
}

async function loadCategoryVideos(categoryId, reset = true, cursor = "") {
    const container = document.getElementById("videos-container");
    const pagination = document.getElementById("videos-pagination");
    if (!container) return;

    if (reset) {
        container.innerHTML = '<div class="loading-placeholder-nav">Cargando videos...</div>';
        videosNextCursor = null;
    }

    const view = document.getElementById("btn-view-feed")?.classList.contains("active") ? "feed" : "channels";
    const watched = document.getElementById("select-filter-watched")?.value || "false";
    const origin = document.getElementById("select-filter-origin")?.value || "all";
    const query = document.getElementById("video-search-input")?.value.trim() || "";

    let url = `/api/v1/videos?limit=24&view=${view}&watched=${watched}&origin=${origin}`;
    if (categoryId) {
        url += `&categoryId=${categoryId}`;
    }
    if (query) url += `&query=${encodeURIComponent(query)}`;
    if (cursor) url += `&cursor=${cursor}`;

    try {
        const response = await apiFetch(url);
        if (response.ok) {
            const data = await response.json();
            const items = data.items || [];
            videosNextCursor = data.nextCursor;

            if (reset) {
                container.innerHTML = "";
            }

            if (items.length === 0 && reset) {
                container.innerHTML = '<div class="loading-placeholder-nav">No hay videos recientes. Prueba agregando canales a esta categoría o sincronizando suscripciones.</div>';
                pagination.classList.add("hidden");
                return;
            }

            if (view === "feed") {
                renderFeedView(container, items);
            } else {
                renderChannelsViewGrouped(container, items);
            }

            // Mostrar/ocultar botón de carga más
            if (videosNextCursor) {
                pagination.classList.remove("hidden");
            } else {
                pagination.classList.add("hidden");
            }
        } else {
            if (reset) {
                container.innerHTML = '<div class="loading-placeholder-nav">Error al consultar los videos.</div>';
            }
        }
    } catch (error) {
        console.error("Error al cargar videos:", error);
        if (reset) {
            container.innerHTML = '<div class="loading-placeholder-nav">Error de conexión al cargar videos.</div>';
        }
    }
}

function renderFeedView(container, videos) {
    // Si es un reset, inicializar grilla
    let grid = container.querySelector(".videos-feed-grid");
    if (!grid) {
        grid = document.createElement("div");
        grid.className = "videos-feed-grid";
        container.appendChild(grid);
    }

    videos.forEach(video => {
        const card = createVideoCard(video);
        grid.appendChild(card);
    });
}

function renderChannelsViewGrouped(container, groups) {
    let listContainer = container.querySelector(".channels-feed-list");
    if (!listContainer) {
        listContainer = document.createElement("div");
        listContainer.className = "channels-feed-list";
        container.appendChild(listContainer);
    }

    groups.forEach((group, groupIdx) => {
        const groupEl = document.createElement("div");
        // El primer canal viene expandido por defecto, los demás colapsados para mantener la vista compacta
        groupEl.className = `channel-video-group-box ${groupIdx === 0 ? "" : "is-collapsed"}`;

        const channel = group.channel;
        const videos = group.videos || [];

        groupEl.innerHTML = `
            <div class="channel-group-header-row">
                <div class="channel-group-header-left">
                    <img src="${channel.thumbnailUrl || ''}" class="channel-avatar-circle" alt="${escapeHtml(channel.title)}">
                    <h3 class="channel-group-title-lbl">${escapeHtml(channel.title)} <span style="font-weight: normal; font-size: 0.95rem; color: var(--text-secondary); margin-left: 6px;">(${videos.length} ${videos.length === 1 ? 'video' : 'videos'})</span></h3>
                </div>
                <div class="channel-group-arrow">▼</div>
            </div>
            <div class="channel-group-videos-container">
                <div class="channel-group-videos-grid">
                    <!-- Videos cargados -->
                </div>
                <div class="channel-group-footer"></div>
            </div>
        `;

        // Alternar colapsado al hacer clic en la cabecera
        const header = groupEl.querySelector(".channel-group-header-row");
        header.addEventListener("click", () => {
            groupEl.classList.toggle("is-collapsed");
        });

        const vGrid = groupEl.querySelector(".channel-group-videos-grid");
        const footer = groupEl.querySelector(".channel-group-footer");

        if (videos.length === 0) {
            vGrid.innerHTML = '<div class="loading-placeholder-nav">Sin videos que coincidan con los filtros.</div>';
        } else {
            videos.forEach((video, videoIdx) => {
                const card = createVideoCard(video);
                // Ocultar videos a partir del cuarto (índice 3 en adelante)
                if (videoIdx >= 3) {
                    card.classList.add("video-hidden");
                }
                vGrid.appendChild(card);
            });

            // Si hay más de 3 videos, mostrar botón de "Ver más"
            if (videos.length > 3) {
                const btnShowMore = document.createElement("button");
                btnShowMore.className = "btn-show-more-videos";
                btnShowMore.textContent = `Ver más (+${videos.length - 3})`;
                btnShowMore.addEventListener("click", (e) => {
                    e.stopPropagation(); // Evitar propagar clics al acordeón
                    groupEl.querySelectorAll(".video-card.video-hidden").forEach(card => {
                        card.classList.remove("video-hidden");
                    });
                    btnShowMore.remove();
                });
                footer.appendChild(btnShowMore);
            }
        }

        listContainer.appendChild(groupEl);
    });
}

function createVideoCard(video) {
    const card = document.createElement("div");
    card.className = `video-card ${video.watched ? "watched-video" : ""}`;
    card.setAttribute("data-video-id", video.id);

    const formattedDuration = formatDuration(video.durationSeconds);
    const durationTag = formattedDuration ? `<span class="video-duration-tag">${formattedDuration}</span>` : "";

    const cleanDate = video.publishedAt ? new Date(video.publishedAt).toLocaleDateString() : "";

    // Insignias
    let badgesHtml = "";
    if (video.origin === "discovery") {
        badgesHtml = '<span class="badge-video-origin-discovery">Descubrimiento</span>';
    }

    card.innerHTML = `
        <div class="video-thumb-wrapper">
            <img src="${video.thumbnailUrl || ''}" class="video-thumb-img" alt="${escapeHtml(video.title)}">
            ${durationTag}
        </div>
        <div class="video-info-section">
            <img src="${video.channel.thumbnailUrl || ''}" class="channel-avatar-circle" alt="${escapeHtml(video.channel.title)}">
            <div class="video-details-text">
                <a class="video-card-title-link">${escapeHtml(video.title)}</a>
                <div class="video-card-meta-row">
                    <span class="video-channel-name-lbl">${escapeHtml(video.channel.title)}</span>
                    <span class="video-date-lbl">${cleanDate}</span>
                </div>
                <div class="video-badges-row">${badgesHtml}</div>
            </div>
            <div class="video-actions-sidebar">
                <button class="btn-toggle-watch ${video.watched ? "is-watched" : ""}" title="${video.watched ? "Marcar como no visto" : "Marcar como visto"}">
                    ${video.watched ? "👁️" : "✓"}
                </button>
            </div>
        </div>
    `;

    // Click en la miniatura o en el título para abrir el video en YouTube y registrar
    const openAction = async (e) => {
        e.preventDefault();
        try {
            const resp = await apiFetch(`/api/v1/videos/${video.id}/open`, { method: "POST" });
            if (resp.ok) {
                const data = await resp.json();
                
                // Marcar como visto localmente al instante
                card.classList.add("watched-video");
                const btnWatch = card.querySelector(".btn-toggle-watch");
                if (btnWatch) {
                    btnWatch.classList.add("is-watched");
                    btnWatch.textContent = "👁️";
                    btnWatch.title = "Marcar como no visto";
                }
                
                window.open(data.url, "_blank");
            }
        } catch (error) {
            console.error("Error al abrir video:", error);
        }
    };

    card.querySelector(".video-thumb-wrapper").addEventListener("click", openAction);
    card.querySelector(".video-card-title-link").addEventListener("click", openAction);

    // Botón de visto / no visto manual
    card.querySelector(".btn-toggle-watch").addEventListener("click", async (e) => {
        e.stopPropagation();
        const currentlyWatched = card.classList.contains("watched-video");
        const newWatchedState = !currentlyWatched;

        try {
            const resp = await apiFetch(`/api/v1/videos/${video.id}/watched`, {
                method: "PUT",
                body: { watched: newWatchedState }
            });

            if (resp.ok) {
                const btnWatch = card.querySelector(".btn-toggle-watch");
                if (newWatchedState) {
                    card.classList.add("watched-video");
                    btnWatch.classList.add("is-watched");
                    btnWatch.textContent = "👁️";
                    btnWatch.title = "Marcar como no visto";
                } else {
                    card.classList.remove("watched-video");
                    btnWatch.classList.remove("is-watched");
                    btnWatch.textContent = "✓";
                    btnWatch.title = "Marcar como visto";
                }
            }
        } catch (error) {
            console.error("Error al alternar estado visto manual:", error);
        }
    });

    return card;
}

function formatDuration(seconds) {
    if (!seconds) return "";
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    let ret = "";
    if (hrs > 0) {
        ret += `${hrs}:${mins.toString().padStart(2, "0")}:`;
    } else {
        ret += `${mins}:`;
    }
    ret += secs.toString().padStart(2, "0");
    return ret;
}

/* --- Vista de Gestión de Canales (Fase 3) --- */

function renderChannelsView() {
    const viewContainer = document.getElementById("view-container");
    if (!viewContainer) return;

    viewContainer.innerHTML = `
        <div class="channels-view">
            <div class="channels-header">
                <h2 class="channels-title">Mis Canales</h2>
                <button id="btn-sync-channels" class="btn-primary">🔄 Sincronizar Suscripciones</button>
            </div>
            
            <div class="channels-toolbar">
                <div class="toolbar-search">
                    <span class="search-icon-inside">🔍</span>
                    <input type="text" id="channel-search-input" placeholder="Buscar canales por título...">
                </div>
                <div class="toolbar-filters">
                    <label class="filter-checkbox-label">
                        <input type="checkbox" id="chk-filter-unclassified"> Solo sin clasificar
                    </label>
                    <label class="filter-checkbox-label">
                        <input type="checkbox" id="chk-filter-subscribed" checked> Solo suscritos
                    </label>
                </div>
            </div>
            
            <div id="channels-grid" class="channels-grid">
                <div class="loading-placeholder-nav">Cargando listado de canales...</div>
            </div>
            
            <div id="channels-pagination" class="pagination-container hidden">
                <button id="btn-channels-load-more" class="btn-secondary">Cargar más canales</button>
            </div>
        </div>
    `;

    // Adjuntar listeners de eventos
    const searchInput = document.getElementById("channel-search-input");
    const chkUnclassified = document.getElementById("chk-filter-unclassified");
    const chkSubscribed = document.getElementById("chk-filter-subscribed");
    const btnLoadMore = document.getElementById("btn-channels-load-more");
    const btnSync = document.getElementById("btn-sync-channels");

    searchInput.addEventListener("input", () => {
        clearTimeout(channelsSearchTimeout);
        channelsSearchTimeout = setTimeout(() => {
            loadChannelsList(true);
        }, 300);
    });

    chkUnclassified.addEventListener("change", () => loadChannelsList(true));
    chkSubscribed.addEventListener("change", () => loadChannelsList(true));

    btnLoadMore.addEventListener("click", () => {
        if (channelsNextCursor) {
            loadChannelsList(false, channelsNextCursor);
        }
    });

    btnSync.addEventListener("click", () => {
        triggerSubscriptionSync();
    });

    // Carga inicial de datos
    loadChannelsList(true);
}

async function loadChannelsList(reset = true, cursor = "") {
    const grid = document.getElementById("channels-grid");
    const pagination = document.getElementById("channels-pagination");
    if (!grid) return;

    if (reset) {
        grid.innerHTML = '<div class="loading-placeholder-nav">Cargando canales...</div>';
        channelsNextCursor = null;
    }

    const query = document.getElementById("channel-search-input")?.value.trim() || "";
    const unclassified = document.getElementById("chk-filter-unclassified")?.checked || false;
    const subscribed = document.getElementById("chk-filter-subscribed")?.checked || false;

    // Construcción de la URL de API
    let url = `/api/v1/channels?limit=30`;
    if (query) url += `&query=${encodeURIComponent(query)}`;
    if (unclassified) url += `&unclassified=true`;
    if (subscribed) url += `&subscribed=true`;
    if (cursor) url += `&cursor=${cursor}`;

    try {
        const response = await apiFetch(url);
        if (response.ok) {
            const data = await response.json();
            const channels = data.items || [];
            channelsNextCursor = data.nextCursor;

            if (reset) {
                grid.innerHTML = "";
            }

            if (channels.length === 0 && reset) {
                grid.innerHTML = '<div class="loading-placeholder-nav">No se encontraron canales. Pruebe re-sincronizando o cambiando filtros.</div>';
                pagination.classList.add("hidden");
                return;
            }

            channels.forEach(channel => {
                const card = document.createElement("div");
                card.className = `channel-card ${channel.blocked ? "blocked-channel" : ""}`;
                
                // Armar insignias
                let badgesHtml = "";
                if (channel.subscribed) badgesHtml += '<span class="badge badge-subscribed">Suscrito</span>';
                if (channel.locallyFollowed) badgesHtml += '<span class="badge badge-followed">Seguido</span>';
                if (channel.blocked) badgesHtml += '<span class="badge badge-blocked">Bloqueado</span>';

                // Mostrar categorías
                let categoriesHtml = "";
                if (channel.categoryIds && channel.categoryIds.length > 0) {
                    channel.categoryIds.forEach(catId => {
                        const catObj = currentCategories.find(c => c.id === catId);
                        if (catObj) {
                            categoriesHtml += `<span class="channel-category-tag">${escapeHtml(catObj.name)}</span>`;
                        }
                    });
                } else {
                    categoriesHtml = '<span class="form-instruction">Sin clasificar</span>';
                }

                card.innerHTML = `
                    <div class="channel-card-top">
                        <img src="${channel.thumbnailUrl || ''}" class="channel-thumbnail" alt="${escapeHtml(channel.title)}">
                        <div class="channel-card-info">
                            <h4 class="channel-card-title">${escapeHtml(channel.title)}</h4>
                            <div class="channel-badges">${badgesHtml}</div>
                        </div>
                    </div>
                    <p class="channel-card-desc">${escapeHtml(channel.description || "Sin descripción")}</p>
                    <div class="channel-card-categories">${categoriesHtml}</div>
                    <div class="channel-card-actions">
                        <button class="btn-secondary btn-sm btn-classify">Categorías</button>
                        <button class="btn-secondary btn-sm btn-block-toggle">${channel.blocked ? "Desbloquear" : "Bloquear"}</button>
                    </div>
                `;

                // Configurar click en clasificar canal (Fase 4)
                card.querySelector(".btn-classify").addEventListener("click", () => {
                    openClassificationModal(channel);
                });

                // Configurar botón de bloqueo
                card.querySelector(".btn-block-toggle").addEventListener("click", async () => {
                    try {
                        const blockResp = await apiFetch(`/api/v1/channels/${channel.id}/block`, {
                            method: "PUT",
                            body: { blocked: !channel.blocked }
                        });
                        if (blockResp.ok) {
                            // Recargar la lista en la página actual
                            loadChannelsList(true);
                        }
                    } catch (error) {
                        console.error("Error al bloquear canal:", error);
                    }
                });

                grid.appendChild(card);
            });

            // Mostrar/ocultar paginación
            if (channelsNextCursor) {
                pagination.classList.remove("hidden");
            } else {
                pagination.classList.add("hidden");
            }
        }
    } catch (error) {
        console.error("Error cargando canales:", error);
        if (reset) {
            grid.innerHTML = '<div class="loading-placeholder-nav">Error de conexión al cargar los canales.</div>';
        }
    }
}

function triggerSubscriptionSync() {
    // Crear y añadir el overlay de carga de sincronización dinámicamente si no existe
    let syncOverlay = document.getElementById("sync-loading-overlay");
    if (!syncOverlay) {
        syncOverlay = document.createElement("div");
        syncOverlay.id = "sync-loading-overlay";
        syncOverlay.className = "sync-overlay";
        syncOverlay.innerHTML = `
            <div class="sync-card">
                <div class="spinner"></div>
                <h3 class="sync-title">Sincronizando con YouTube</h3>
                <p class="sync-subtitle">Esto puede demorar unos segundos. Importando suscripciones, canales y videos recientes...</p>
            </div>
        `;
        document.body.appendChild(syncOverlay);
    }
    
    syncOverlay.classList.remove("hidden");

    apiFetch("/api/v1/channels/sync", { method: "POST" })
        .then(response => {
            if (response.ok) {
                return response.json();
            }
            throw new Error("Fallo en sincronización externa.");
        })
        .then(result => {
            syncOverlay.classList.add("hidden");
            showAlertDialog(
                "Sincronización Completa",
                `Sincronización completa:\n- Suscripciones creadas: ${result.created}\n- Suscripciones actualizadas: ${result.updated}\n- Videos nuevos importados: ${result.videos_created}\n- Videos actualizados: ${result.videos_updated}\n- Canales procesados: ${result.processed_channels}`
            );
            
            // Recargar la vista actual para reflejar los nuevos videos/canales
            handleCurrentRoute();
        })
        .catch(error => {
            console.error("Error en sincronización:", error);
            syncOverlay.classList.add("hidden");
            showAlertDialog(
                "Error de Sincronización",
                "Error al sincronizar con YouTube. Verifique que sus credenciales OAuth estén bien configuradas."
            );
        });
}

/* --- Clasificador Manual de Canales (Fase 4) --- */

function setupChannelClassifier() {
    const modal = document.getElementById("channel-classification-modal");
    const btnClose = document.getElementById("btn-close-classification-modal");
    const btnCancel = document.getElementById("btn-cancel-classification");
    const form = document.getElementById("channel-classification-form");

    if (!modal) return;

    const closeModal = () => {
        modal.classList.add("hidden");
        form.reset();
    };

    btnClose.addEventListener("click", closeModal);
    btnCancel.addEventListener("click", closeModal);

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const channelId = document.getElementById("class-channel-id").value;
        const errEl = document.getElementById("classification-form-error");

        errEl.classList.add("hidden");
        errEl.textContent = "";

        // Obtener los IDs de las categorías seleccionadas
        const checkboxes = document.querySelectorAll("#classification-categories-checkboxes input[type='checkbox']");
        const categoryIds = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => parseInt(cb.value));

        try {
            const response = await apiFetch(`/api/v1/channels/${channelId}/categories`, {
                method: "PUT",
                body: { categoryIds }
            });

            if (response.ok) {
                closeModal();
                loadChannelsList(true); // Recargar grilla de canales
                loadCategories();       // Actualizar conteos en barra lateral
            } else {
                const errData = await response.json();
                errEl.textContent = errData.error?.message || "Fallo al guardar la clasificación.";
                errEl.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Error en guardar clasificación:", error);
            errEl.textContent = "Error de conexión con el servidor.";
            errEl.classList.remove("hidden");
        }
    });
}

function openClassificationModal(channel) {
    const modal = document.getElementById("channel-classification-modal");
    if (!modal) return;

    document.getElementById("class-channel-id").value = channel.id;
    
    // Hidratar info básica del canal
    const thumbEl = document.getElementById("class-channel-thumb");
    thumbEl.src = channel.thumbnailUrl || "";
    thumbEl.alt = channel.title;

    document.getElementById("class-channel-title").textContent = channel.title;
    document.getElementById("class-channel-desc").textContent = channel.description || "Sin descripción";

    // Generar checkboxes de categorías
    const container = document.getElementById("classification-categories-checkboxes");
    container.innerHTML = "";

    if (currentCategories.length === 0) {
        container.innerHTML = "<p class='form-instruction'>No existen categorías creadas. Crea una en el menú lateral primero.</p>";
    } else {
        currentCategories.forEach(cat => {
            const isChecked = channel.categoryIds.includes(cat.id);
            const label = document.createElement("label");
            label.className = "checkbox-item-label";
            label.innerHTML = `
                <input type="checkbox" value="${cat.id}" ${isChecked ? "checked" : ""}>
                <span>${escapeHtml(cat.name)}</span>
            `;
            container.appendChild(label);
        });
    }

    // Mostrar modal
    modal.classList.remove("hidden");
    document.getElementById("classification-form-error").classList.add("hidden");
}

/* --- Administrador de Categorías (Fase 2) --- */

function setupCategoryManager() {
    const btnManage = document.getElementById("btn-manage-categories");
    const modal = document.getElementById("categories-modal");
    const btnCloseModal = document.getElementById("btn-close-categories-modal");
    const btnAddCategory = document.getElementById("btn-add-category");
    const btnCancelForm = document.getElementById("btn-cancel-category-form");
    const form = document.getElementById("category-form");
    
    const btnAddKw = document.getElementById("btn-add-kw");
    const kwWeightInput = document.getElementById("kw-weight-input");
    const kwWeightValue = document.getElementById("kw-weight-value");

    if (!modal) return;

    // Abrir/Cerrar Modal
    btnManage.addEventListener("click", () => {
        modal.classList.remove("hidden");
        loadManageCategories();
        hideCategoryForm();
    });

    btnCloseModal.addEventListener("click", () => {
        modal.classList.add("hidden");
    });

    // Cambiar al formulario
    btnAddCategory.addEventListener("click", () => {
        showCategoryForm();
    });

    btnCancelForm.addEventListener("click", () => {
        hideCategoryForm();
    });

    // Control de slider de peso en palabra clave
    kwWeightInput.addEventListener("input", (e) => {
        kwWeightValue.textContent = parseFloat(e.target.value).toFixed(1);
    });

    // Agregar palabra clave al array temporal
    btnAddKw.addEventListener("click", () => {
        const termInput = document.getElementById("kw-term-input");
        const polaritySelect = document.getElementById("kw-polarity-select");
        
        const term = termInput.value.trim();
        const polarity = polaritySelect.value;
        const weight = parseFloat(kwWeightInput.value);

        if (!term) return;

        // Comprobar duplicado en la interfaz
        if (activeFormKeywords.some(k => k.term.toLowerCase() === term.toLowerCase())) {
            showAlertDialog("Término Duplicado", "Este término ya está añadido.");
            return;
        }

        activeFormKeywords.push({ term, polarity, weight });
        renderKeywordTags();
        
        // Reset inputs
        termInput.value = "";
        kwWeightInput.value = "1.0";
        kwWeightValue.textContent = "1.0";
    });

    // Guardar Categoría (Submit Form)
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const id = document.getElementById("form-category-id").value;
        const name = document.getElementById("category-name-input").value.trim();
        const description = document.getElementById("category-desc-input").value.trim();
        const formError = document.getElementById("category-form-error");

        formError.classList.add("hidden");
        formError.textContent = "";

        const payload = {
            name,
            description,
            keywords: activeFormKeywords
        };

        const url = id ? `/api/v1/categories/${id}` : "/api/v1/categories";
        const method = id ? "PUT" : "POST";

        try {
            const response = await apiFetch(url, {
                method,
                body: payload
            });

            if (response.ok) {
                hideCategoryForm();
                loadManageCategories();
                loadCategories(); // Refrescar el sidebar
            } else {
                const errData = await response.json();
                formError.textContent = errData.error?.message || "Error al guardar la categoría.";
                formError.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Error al guardar categoría:", error);
            formError.textContent = "Error de conexión con el servidor.";
            formError.classList.remove("hidden");
        }
    });
}

function showCategoryForm(category = null) {
    const listView = document.getElementById("categories-list-view");
    const form = document.getElementById("category-form");
    const modalTitle = document.querySelector(".categories-modal-card .modal-title");
    const formError = document.getElementById("category-form-error");

    listView.classList.add("hidden");
    form.classList.remove("hidden");
    formError.classList.add("hidden");
    form.reset();

    if (category) {
        modalTitle.textContent = "Editar Categoría";
        document.getElementById("form-category-id").value = category.id;
        document.getElementById("category-name-input").value = category.name;
        document.getElementById("category-desc-input").value = category.description || "";
        activeFormKeywords = [...(category.keywords || [])];
    } else {
        modalTitle.textContent = "Nueva Categoría";
        document.getElementById("form-category-id").value = "";
        activeFormKeywords = [];
    }

    renderKeywordTags();
}

function hideCategoryForm() {
    const listView = document.getElementById("categories-list-view");
    const form = document.getElementById("category-form");
    const modalTitle = document.querySelector(".categories-modal-card .modal-title");

    listView.classList.remove("hidden");
    form.classList.add("hidden");
    modalTitle.textContent = "Gestionar Categorías";
    form.reset();
}

function renderKeywordTags() {
    const container = document.getElementById("category-keywords-tags");
    if (!container) return;

    container.innerHTML = "";
    if (activeFormKeywords.length === 0) {
        container.innerHTML = '<span class="form-instruction">No hay palabras clave configuradas.</span>';
        return;
    }

    activeFormKeywords.forEach((kw, index) => {
        const tag = document.createElement("span");
        tag.className = `keyword-tag tag-${kw.polarity}`;
        tag.innerHTML = `
            <span>${escapeHtml(kw.term)}</span>
            <span class="keyword-tag-weight">${kw.weight.toFixed(1)}</span>
            <button type="button" class="btn-remove-tag" data-index="${index}">&times;</button>
        `;

        tag.querySelector(".btn-remove-tag").addEventListener("click", () => {
            activeFormKeywords.splice(index, 1);
            renderKeywordTags();
        });

        container.appendChild(tag);
    });
}

async function loadManageCategories() {
    const listContainer = document.getElementById("categories-manage-list");
    if (!listContainer) return;

    listContainer.innerHTML = '<div class="loading-placeholder-nav">Cargando categorías...</div>';

    try {
        const response = await apiFetch("/api/v1/categories");
        if (response.ok) {
            const data = await response.json();
            const categories = data.items || [];
            listContainer.innerHTML = "";

            if (categories.length === 0) {
                listContainer.innerHTML = '<div class="loading-placeholder-nav">No hay categorías. Crea una para empezar.</div>';
                return;
            }

            categories.forEach((cat, idx) => {
                const item = document.createElement("div");
                item.className = "manage-item";
                item.innerHTML = `
                    <div class="manage-item-info">
                        <span class="manage-item-name">${escapeHtml(cat.name)}</span>
                        <span class="manage-item-desc">${escapeHtml(cat.description || "Sin descripción")}</span>
                    </div>
                    <div class="manage-item-actions">
                        <button class="btn-icon-sm btn-up" title="Subir" ${idx === 0 ? "disabled" : ""}>▲</button>
                        <button class="btn-icon-sm btn-down" title="Bajar" ${idx === categories.length - 1 ? "disabled" : ""}>▼</button>
                        <button class="btn-icon-sm btn-edit" title="Editar">✏️</button>
                        <button class="btn-icon-sm btn-delete" title="Eliminar">🗑️</button>
                    </div>
                `;

                // Subir categoría
                item.querySelector(".btn-up")?.addEventListener("click", () => {
                    moveCategory(categories, idx, idx - 1);
                });

                // Bajar categoría
                item.querySelector(".btn-down")?.addEventListener("click", () => {
                    moveCategory(categories, idx, idx + 1);
                });

                // Editar categoría
                item.querySelector(".btn-edit").addEventListener("click", () => {
                    showCategoryForm(cat);
                });

                // Eliminar categoría
                item.querySelector(".btn-delete").addEventListener("click", async () => {
                    const confirmed = await showConfirmDialog(
                        "Eliminar Categoría",
                        `¿Estás seguro de que deseas eliminar la categoría "${cat.name}"? Los canales y videos no se borrarán.`
                    );
                    if (confirmed) {
                        try {
                            const delResp = await apiFetch(`/api/v1/categories/${cat.id}`, { method: "DELETE" });
                            if (delResp.ok) {
                                loadManageCategories();
                                loadCategories(); // Refrescar el sidebar
                            }
                        } catch (err) {
                            console.error("Error al eliminar categoría:", err);
                        }
                    }
                });

                listContainer.appendChild(item);
            });
        }
    } catch (error) {
        console.error("Error cargando gestor de categorías:", error);
        listContainer.innerHTML = '<div class="loading-placeholder-nav">Error de conexión.</div>';
    }
}

async function moveCategory(categories, fromIdx, toIdx) {
    // Reordenar localmente
    const element = categories.splice(fromIdx, 1)[0];
    categories.splice(toIdx, 0, element);

    // Mapear los IDs en el nuevo orden
    const categoryIds = categories.map(c => c.id);

    try {
        const response = await apiFetch("/api/v1/categories/reorder", {
            method: "PUT",
            body: { categoryIds }
        });

        if (response.ok) {
            loadManageCategories();
            loadCategories(); // Refrescar el sidebar en el orden correcto
        }
    } catch (error) {
        console.error("Error al reordenar categorías:", error);
    }
}

function setupRefreshButton() {
    const btnRefresh = document.getElementById("btn-refresh");
    if (btnRefresh) {
        btnRefresh.addEventListener("click", () => {
            triggerSubscriptionSync();
        });
    }
}

function showAlertDialog(title, message) {
    const dialogId = "custom-alert-dialog";
    document.getElementById(dialogId)?.remove();

    const overlay = document.createElement("div");
    overlay.id = dialogId;
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
        <div class="modal-card" style="max-width: 450px;">
            <div class="modal-header">
                <h3 class="modal-title">${escapeHtml(title)}</h3>
                <button class="btn-close-modal" id="btn-close-alert">&times;</button>
            </div>
            <div class="modal-body" style="padding: 20px;">
                <p style="color: #cbd5e1; line-height: 1.6; margin: 0 0 20px 0; font-size: 0.95rem;">${message.replace(/\n/g, "<br>")}</p>
                <div style="display: flex; justify-content: flex-end;">
                    <button class="btn-primary" id="btn-alert-ok">Aceptar</button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    const close = () => {
        overlay.classList.add("hidden");
        setTimeout(() => overlay.remove(), 300);
    };

    document.getElementById("btn-close-alert").addEventListener("click", close);
    document.getElementById("btn-alert-ok").addEventListener("click", close);
}

function showConfirmDialog(title, message) {
    return new Promise((resolve) => {
        const dialogId = "custom-confirm-dialog";
        document.getElementById(dialogId)?.remove();

        const overlay = document.createElement("div");
        overlay.id = dialogId;
        overlay.className = "modal-overlay";
        overlay.innerHTML = `
            <div class="modal-card" style="max-width: 450px;">
                <div class="modal-header">
                    <h3 class="modal-title">${escapeHtml(title)}</h3>
                    <button class="btn-close-modal" id="btn-close-confirm">&times;</button>
                </div>
                <div class="modal-body" style="padding: 20px;">
                    <p style="color: #cbd5e1; line-height: 1.6; margin: 0 0 20px 0; font-size: 0.95rem;">${escapeHtml(message)}</p>
                    <div style="display: flex; justify-content: flex-end; gap: 10px;">
                        <button class="btn-secondary" id="btn-confirm-cancel">Cancelar</button>
                        <button class="btn-primary" id="btn-confirm-ok">Confirmar</button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        const close = (result) => {
            overlay.classList.add("hidden");
            setTimeout(() => {
                overlay.remove();
                resolve(result);
            }, 300);
        };

        document.getElementById("btn-close-confirm").addEventListener("click", () => close(false));
        document.getElementById("btn-confirm-cancel").addEventListener("click", () => close(false));
        document.getElementById("btn-confirm-ok").addEventListener("click", () => close(true));
    });
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}
