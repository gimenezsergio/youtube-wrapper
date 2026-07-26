// YouTube Curator — Main Application Entry (ES Module)

document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

function initApp() {
    console.log("YouTube Curator inicializado...");
    
    // Configurar menú móvil
    setupMobileMenu();
    
    // Verificar estado de autenticación inicial
    checkAuthStatus();
    
    // Cargar categorías iniciales
    loadCategories();
    
    // Configurar manejador del botón de actualización
    setupRefreshButton();
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

async function checkAuthStatus() {
    const userEmailEl = document.getElementById("user-email");
    const userInfoEl = userEmailEl ? userEmailEl.parentElement : null;
    
    try {
        const response = await fetch("/api/v1/auth/status");
        if (response.ok) {
            const data = await response.json();
            if (data.authenticated) {
                if (userEmailEl) userEmailEl.textContent = data.email || "Conectado";
                if (userInfoEl) userInfoEl.classList.add("online");
            } else {
                if (userEmailEl) userEmailEl.textContent = "Sin conexión";
                if (userInfoEl) userInfoEl.classList.remove("online");
            }
        }
    } catch (error) {
        console.error("Error al obtener estado de autenticación:", error);
    }
}

async function loadCategories() {
    const categoriesList = document.getElementById("sidebar-categories");
    if (!categoriesList) return;
    
    try {
        const response = await fetch("/api/v1/categories");
        if (response.ok) {
            const data = await response.json();
            categoriesList.innerHTML = "";
            
            if (!data.items || data.items.length === 0) {
                categoriesList.innerHTML = '<div class="loading-placeholder-nav">Sin categorías</div>';
                return;
            }
            
            data.items.forEach(category => {
                const item = document.createElement("a");
                item.href = `/category/${category.id}`;
                item.className = "nav-item";
                item.innerHTML = `
                    <span class="nav-icon">📁</span>
                    <span class="nav-label">${escapeHtml(category.name)}</span>
                `;
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

function setupRefreshButton() {
    const btnRefresh = document.getElementById("btn-refresh");
    if (btnRefresh) {
        btnRefresh.addEventListener("click", () => {
            // En Fase 0 solo mostramos una simulación visual o llamamos al endpoint de refresh si existe
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
