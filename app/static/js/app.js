// YouTube Curator — Main Application Entry (ES Module)

let csrfToken = null;
let activeFormKeywords = []; // Array temporal para las keywords en el formulario
let currentCategories = []; // Array con el listado actual de categorías cargadas

document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

function initApp() {
    console.log("YouTube Curator inicializado...");
    
    // Configurar menú móvil
    setupMobileMenu();
    
    // Verificar estado de autenticación inicial
    checkAuthStatus();
    
    // Configurar manejador del botón de actualización
    setupRefreshButton();

    // Configurar administrador de categorías (Fase 2)
    setupCategoryManager();
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
                // Cargar categorías una vez autenticado
                loadCategories();
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
            
            // Si la URL ya tiene una categoría seleccionada en la query string, activarla
            const urlParams = new URLSearchParams(window.location.search);
            const activeCatId = urlParams.get("category");
            if (activeCatId) {
                selectCategoryInSidebar(parseInt(activeCatId));
            }
        } else {
            categoriesList.innerHTML = '<div class="loading-placeholder-nav">Error al cargar</div>';
        }
    } catch (error) {
        console.error("Error cargando categorías:", error);
        categoriesList.innerHTML = '<div class="loading-placeholder-nav">Error de conexión</div>';
    }
}

function selectCategoryInSidebar(categoryId) {
    // Quitar active de todas
    document.querySelectorAll(".sidebar-nav .nav-item").forEach(el => el.classList.remove("active"));
    
    // Añadir active a la seleccionada
    const activeItem = document.querySelector(`.sidebar-nav .nav-item[data-category-id="${categoryId}"]`);
    if (activeItem) {
        activeItem.classList.add("active");
    }
    
    // Actualizar la URL de manera SPA (Fase 2)
    const url = new URL(window.location.href);
    url.searchParams.set("category", categoryId);
    window.history.pushState({}, "", url.toString());
    
    // Cargar el feed de esa categoría (Se implementará en Fase 5/8/9, ahora solo dejamos logueado)
    console.log(`Navegando a la categoría ID: ${categoryId}`);
}

/* --- Administrador de Categorías (Fase 2) --- */

function setupCategoryManager() {
    const btnManage = document.getElementById("btn-manage-categories");
    const modal = document.getElementById("categories-modal");
    const btnCloseModal = document.getElementById("btn-close-categories-modal");
    const btnAddCategory = document.getElementById("btn-add-category");
    const btnCancelForm = document.getElementById("btn-cancel-category-form");
    const form = document.getElementById("category-form");
    
    const listView = document.getElementById("categories-list-view");
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
            alert("Este término ya está añadido.");
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
                    if (confirm(`¿Estás seguro de que deseas eliminar la categoría "${cat.name}"? Los canales y videos no se borrarán.`)) {
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
            triggerRefreshRun();
        });
    }
}

async function triggerRefreshRun() {
    const overlay = document.getElementById("refresh-overlay");
    const progressBar = document.getElementById("refresh-progress-bar");
    const stageEl = document.getElementById("refresh-stage");
    
    if (!overlay) return;
    
    overlay.classList.remove("hidden");
    if (progressBar) progressBar.style.width = "0%";
    if (stageEl) stageEl.textContent = "Iniciando actualización...";
    
    // Simular un progreso en Fase 0
    let progress = 0;
    const stages = [
        "Importando suscripciones de YouTube...",
        "Analizando metadatos de canales...",
        "Buscando videos recientes...",
        "Clasificando automáticamente...",
        "Generando candidatos de descubrimiento...",
        "Finalizando actualización..."
    ];
    
    const interval = setInterval(() => {
        progress += 16.6;
        const stageIndex = Math.min(Math.floor(progress / 16.6), stages.length - 1);
        
        if (progressBar) progressBar.style.width = `${Math.min(progress, 100)}%`;
        if (stageEl) stageEl.textContent = stages[stageIndex];
        
        if (progress >= 100) {
            clearInterval(interval);
            setTimeout(() => {
                overlay.classList.add("hidden");
            }, 800);
        }
    }, 500);
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}
