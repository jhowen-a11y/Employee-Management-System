    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (window.lucide) {
        window.lucide.createIcons();
    }

    const searchTimers = new WeakMap();
    document.addEventListener("input", function (event) {
        const input = event.target;
        if (
            !(input instanceof HTMLInputElement) ||
            input.type !== "search" ||
            !input.form ||
            !input.form.hasAttribute("data-search-debounce")
        ) {
            return;
        }

        window.clearTimeout(searchTimers.get(input));
        const form = input.form;
        searchTimers.set(input, window.setTimeout(function () {
            if (form && form.isConnected) {
                form.requestSubmit();
            }
        }, 350));
    });
    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-search-debounce")) {
            return;
        }

        form.querySelectorAll('input[type="search"]').forEach(function (input) {
            window.clearTimeout(searchTimers.get(input));
        });
        form.setAttribute("aria-busy", "true");
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.textContent = "Loading results...";
            submitButton.disabled = true;
        }
    });

    const deleteDialog = document.getElementById("deleteDialog");
    const deleteTitle = document.getElementById("deleteDialogTitle");
    const deleteMessage = document.getElementById("deleteDialogMessage");
    const cancelDelete = document.getElementById("cancelDelete");
    const confirmDelete = document.getElementById("confirmDelete");
    let pendingDeleteForm = null;
    let confirmedDeleteForm = null;

    if (deleteDialog && deleteTitle && deleteMessage && cancelDelete && confirmDelete) {
        document.addEventListener("submit", function (event) {
            const form = event.target;
            if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm-delete")) {
                return;
            }

            if (confirmedDeleteForm === form) {
                confirmedDeleteForm = null;
                return;
            }

            event.preventDefault();
            pendingDeleteForm = form;
            deleteTitle.textContent = form.dataset.deleteTitle || "Delete this record?";
            deleteMessage.textContent = form.dataset.deleteMessage || "This action cannot be undone.";

            if (typeof deleteDialog.showModal === "function") {
                deleteDialog.showModal();
                cancelDelete.focus();
            } else if (window.confirm(deleteTitle.textContent + "\n\n" + deleteMessage.textContent)) {
                pendingDeleteForm = null;
                confirmedDeleteForm = form;
                form.requestSubmit();
            }
        });

        cancelDelete.addEventListener("click", function () {
            pendingDeleteForm = null;
            deleteDialog.close();
        });

        deleteDialog.addEventListener("cancel", function () {
            pendingDeleteForm = null;
        });

        confirmDelete.addEventListener("click", function () {
            if (!pendingDeleteForm) {
                return;
            }
            const form = pendingDeleteForm;
            pendingDeleteForm = null;
            confirmedDeleteForm = form;
            deleteDialog.close();
            form.requestSubmit();
        });
    }

    document.querySelectorAll("[data-password-toggle]").forEach(function (toggle) {
        const password = document.getElementById(toggle.getAttribute("aria-controls"));

        if (!password) {
            return;
        }

        toggle.addEventListener("click", function () {
            const isVisible = password.type === "text";
            password.type = isVisible ? "password" : "text";
            toggle.innerHTML = '<i data-lucide="' + (isVisible ? "eye-off" : "eye") + '" aria-hidden="true"></i>';
            toggle.setAttribute("aria-label", isVisible ? "Show password" : "Hide password");
            toggle.setAttribute("aria-pressed", String(!isVisible));

            if (window.lucide) {
                window.lucide.createIcons();
            }
        });
    });

    if (menuToggle && sidebar) {
        menuToggle.addEventListener("click", function () {
            sidebar.classList.toggle("open");
        });

        document.addEventListener("click", function (event) {
            if (
                window.innerWidth <= 800 &&
                !sidebar.contains(event.target) &&
                !menuToggle.contains(event.target)
            ) {
                sidebar.classList.remove("open");
            }
        });
    }

    (function enableClientNavigation() {
        const main = document.querySelector("main.content");
        const navigation = document.querySelector(".nav-links");
        if (
            !main ||
            !navigation ||
            !window.fetch ||
            !window.AbortController ||
            !window.history.pushState
        ) {
            return;
        }

        const skeletonDelay = 160;
        let activeController = null;
        let activeUrl = null;
        let navigationId = 0;
        let skeletonTimer = null;

        function getSkeletonId(url) {
            const path = url.pathname.replace(/\/+$/, "") || "/";
            const role = document.body.dataset.userRole;

            if (path === "/" || path === "/hr/home") {
                return role === "employee"
                    ? "skeleton-employee-dashboard"
                    : "skeleton-dashboard";
            }
            if (path === "/employee/home") {
                return "skeleton-employee-dashboard";
            }
            if (path === "/payroll" || /^\/payroll\/\d+$/.test(path)) {
                return /^\/payroll\/\d+$/.test(path)
                    ? "skeleton-detail"
                    : "skeleton-payroll-list";
            }
            if (path === "/employees" || /^\/employees\/\d+$/.test(path)) {
                return /^\/employees\/\d+$/.test(path)
                    ? "skeleton-detail"
                    : "skeleton-employee-list";
            }
            if (/\/(add|edit|submit)$/.test(path)) {
                return "skeleton-form";
            }
            if (/\/\d+$/.test(path)) {
                return "skeleton-detail";
            }
            return "skeleton-list";
        }

        function loadingTitle(url) {
            const path = url.pathname;
            if (path.indexOf("/payroll") === 0) return "Payroll";
            if (path.indexOf("/employees") === 0) return "Employees";
            if (path.indexOf("/attendance") === 0) return "Attendance";
            if (path.indexOf("/departments") === 0) return "Departments";
            if (path.indexOf("/leave") === 0) return "Leave";
            if (path.indexOf("/payslips") === 0) return "Payslips";
            if (path.indexOf("/travel-orders") === 0) return "Travel orders";
            if (path === "/employee/home") return "My Home";
            return "Dashboard";
        }

        function showSkeleton(url) {
            const template = document.getElementById(getSkeletonId(url));
            if (!template) return;

            main.replaceChildren(template.content.cloneNode(true));
            main.setAttribute("aria-busy", "true");
            const title = document.querySelector(".topbar h2");
            if (title) title.textContent = "Loading " + loadingTitle(url);
        }

        function showNavigationError(url) {
            const section = document.createElement("section");
            section.className = "panel navigation-error";
            section.setAttribute("role", "alert");

            const heading = document.createElement("h1");
            heading.textContent = "This page could not be loaded";
            const message = document.createElement("p");
            message.textContent = "Check your connection and try again.";
            const retry = document.createElement("button");
            retry.className = "button button-primary";
            retry.type = "button";
            retry.dataset.retryNavigation = url.href;
            retry.textContent = "Retry";

            section.append(heading, message, retry);
            main.replaceChildren(section);
            main.setAttribute("aria-busy", "false");
            const title = document.querySelector(".topbar h2");
            if (title) title.textContent = "Page unavailable";
        }

        async function loadPage(url, addHistory) {
            if (activeUrl === url.href) return;
            if (activeController) activeController.abort();
            window.clearTimeout(skeletonTimer);

            const controller = new AbortController();
            activeController = controller;
            activeUrl = url.href;
            const currentNavigationId = ++navigationId;
            let navigationTimedOut = false;
            const requestTimeout = window.setTimeout(function () {
                navigationTimedOut = true;
                controller.abort();
            }, 30000);
            main.setAttribute("aria-busy", "true");
            skeletonTimer = window.setTimeout(function () {
                if (currentNavigationId === navigationId) showSkeleton(url);
            }, skeletonDelay);

            try {
                const response = await window.fetch(url.href, {
                    method: "GET",
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    signal: controller.signal
                });
                const contentType = response.headers.get("content-type") || "";
                if (!contentType.toLowerCase().includes("text/html")) {
                    window.location.assign(response.url || url.href);
                    return;
                }

                const page = new DOMParser().parseFromString(
                    await response.text(),
                    "text/html"
                );
                const destination = new URL(response.url || url.href);
                if (destination.pathname === "/login") {
                    window.location.assign(destination.href);
                    return;
                }
                const nextMain = page.querySelector("main.content");
                if (!nextMain || !page.querySelector(".app")) {
                    if (!response.ok) {
                        throw new Error(
                            "Page request failed with status " + response.status
                        );
                    }
                    window.location.assign(destination.href);
                    return;
                }
                if (
                    nextMain.querySelector(
                        "script, [onclick], [onchange], [onsubmit], [data-password-toggle]"
                    )
                ) {
                    window.location.assign(response.url || url.href);
                    return;
                }
                if (destination.origin !== window.location.origin) {
                    window.location.assign(destination.href);
                    return;
                }
                if (!response.ok) {
                    throw new Error("Page request failed with status " + response.status);
                }

                window.clearTimeout(skeletonTimer);
                window.clearTimeout(requestTimeout);
                main.innerHTML = nextMain.innerHTML;
                main.setAttribute("aria-busy", "false");

                const nextTitle = page.querySelector(".topbar h2");
                const title = document.querySelector(".topbar h2");
                if (title && nextTitle) title.textContent = nextTitle.textContent;
                if (page.title) document.title = page.title;

                const nextNavigation = page.querySelector(".nav-links");
                if (nextNavigation) navigation.innerHTML = nextNavigation.innerHTML;

                if (addHistory) {
                    window.history.pushState({}, "", destination.href);
                }
                activeUrl = null;
                activeController = null;
                if (window.lucide) window.lucide.createIcons();
                if (addHistory) window.scrollTo(0, 0);
            } catch (error) {
                if (controller.signal.aborted || currentNavigationId !== navigationId) {
                    if (!navigationTimedOut) return;
                }
                if (currentNavigationId !== navigationId) {
                    return;
                }
                window.clearTimeout(skeletonTimer);
                window.clearTimeout(requestTimeout);
                console.error("Client-side navigation failed:", error);
                showNavigationError(url);
                activeUrl = null;
                activeController = null;
            } finally {
                window.clearTimeout(requestTimeout);
            }
        }

        document.addEventListener("click", function (event) {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }

            const link = event.target instanceof Element
                ? event.target.closest("a")
                : null;
            if (
                !link ||
                link.target ||
                link.hasAttribute("download") ||
                link.relList.contains("external")
            ) {
                return;
            }

            const url = new URL(link.href, window.location.href);
            if (
                url.origin !== window.location.origin ||
                url.href === window.location.href ||
                (
                    url.pathname === window.location.pathname &&
                    url.search === window.location.search &&
                    url.hash
                ) ||
                url.pathname.endsWith("/download") ||
                url.pathname === "/users/api" ||
                /^\/users\/(?:add|profile|[^/]+\/edit)/.test(url.pathname)
            ) {
                return;
            }

            event.preventDefault();
            loadPage(url, true);
        });

        document.addEventListener("click", function (event) {
            const retry = event.target instanceof Element
                ? event.target.closest("[data-retry-navigation]")
                : null;
            if (retry) {
                loadPage(new URL(retry.dataset.retryNavigation), true);
            }
        });

        window.addEventListener("popstate", function () {
            loadPage(new URL(window.location.href), false);
        });
    })();
