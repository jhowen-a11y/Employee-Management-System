    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (window.lucide) {
        window.lucide.createIcons();
    }

    function parseRangeDate(value) {
        const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
        if (!match) {
            return null;
        }
        const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
        return date.getFullYear() === Number(match[1]) &&
            date.getMonth() === Number(match[2]) - 1 &&
            date.getDate() === Number(match[3])
            ? date
            : null;
    }

    function rangeDateValue(date) {
        return [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, "0"),
            String(date.getDate()).padStart(2, "0")
        ].join("-");
    }

    function formatRangeDate(value) {
        const date = parseRangeDate(value);
        return date
            ? new Intl.DateTimeFormat(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric"
            }).format(date)
            : "";
    }

    function updateDateRangeDisplay(range) {
        const from = range.querySelector("[data-range-from]");
        const to = range.querySelector("[data-range-to]");
        const display = range.querySelector("[data-range-display]");
        const clear = range.querySelector("[data-range-clear]");
        const toggle = range.querySelector("[data-range-toggle]");
        const instruction = range.querySelector("[data-range-instructions]");
        const done = range.querySelector("[data-range-done]");

        range.dataset.dateFrom = from.value;
        range.dataset.dateTo = to.value;
        if (from.value && to.value) {
            display.textContent = formatRangeDate(from.value) + " – " + formatRangeDate(to.value);
            instruction.textContent = "Date range selected";
            done.hidden = false;
        } else if (from.value) {
            display.textContent = formatRangeDate(from.value) + " – Choose end date";
            instruction.textContent = "Select an end date";
            done.hidden = true;
        } else {
            display.textContent = "Choose dates";
            instruction.textContent = "Select a start date";
            done.hidden = true;
        }
        clear.hidden = !from.value && !to.value;
        const error = range.querySelector("[data-range-error]");
        if (error && from.value && to.value) {
            error.hidden = true;
            toggle.removeAttribute("aria-invalid");
        }
    }

    function renderDateRangeCalendar(range) {
        const monthLabel = range.querySelector("[data-range-month]");
        const days = range.querySelector("[data-range-days]");
        const instructions = range.querySelector("[data-range-instructions]");
        const from = range.querySelector("[data-range-from]").value;
        const to = range.querySelector("[data-range-to]").value;
        const mode = range.dataset.rangeMode || "start";
        const month = new Date(
            Number(range.dataset.viewYear),
            Number(range.dataset.viewMonth),
            1
        );
        const year = month.getFullYear();
        const monthIndex = month.getMonth();
        const firstWeekday = new Date(year, monthIndex, 1).getDay();
        const dayCount = new Date(year, monthIndex + 1, 0).getDate();

        monthLabel.textContent = new Intl.DateTimeFormat(undefined, {
            month: "long",
            year: "numeric"
        }).format(month);
        instructions.textContent = mode === "end"
            ? "Select an end date"
            : "Select a start date";
        days.replaceChildren();

        for (let index = 0; index < firstWeekday + dayCount; index += 1) {
            if (index < firstWeekday) {
                const spacer = document.createElement("span");
                spacer.setAttribute("aria-hidden", "true");
                days.append(spacer);
                continue;
            }

            const day = index - firstWeekday + 1;
            const date = new Date(year, monthIndex, day);
            const value = rangeDateValue(date);
            const button = document.createElement("button");
            button.type = "button";
            button.className = "date-range-day";
            button.textContent = String(day);
            button.dataset.rangeDate = value;
            button.setAttribute("aria-label", new Intl.DateTimeFormat(undefined, {
                dateStyle: "full"
            }).format(date));

            const isStart = value === from;
            const isEnd = value === to;
            const isBetween = from && to && value >= from && value <= to;
            if (isStart) button.classList.add("is-range-start");
            if (isEnd) button.classList.add("is-range-end");
            if (isBetween) button.classList.add("is-in-range");
            if (value === rangeDateValue(new Date())) button.classList.add("is-today");
            button.setAttribute("aria-pressed", String(isStart || isEnd));
            button.tabIndex = value === range.dataset.focusDate ? 0 : -1;

            if (mode === "end" && from && value < from) {
                button.disabled = true;
            }
            days.append(button);
        }
    }

    function closeDateRange(range, returnFocus) {
        const toggle = range.querySelector("[data-range-toggle]");
        const popover = range.querySelector(".date-range-popover");
        popover.hidden = true;
        range.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        if (returnFocus) toggle.focus();
    }

    function focusDateRangeDay(range, value) {
        const date = parseRangeDate(value);
        if (!date) {
            return;
        }
        range.dataset.focusDate = value;
        range.dataset.viewYear = String(date.getFullYear());
        range.dataset.viewMonth = String(date.getMonth());
        renderDateRangeCalendar(range);
        const day = range.querySelector('[data-range-date="' + value + '"]');
        if (day && !day.disabled) {
            day.focus();
        }
    }

    function openDateRange(range) {
        document.querySelectorAll("[data-date-range].is-open").forEach(function (openRange) {
            if (openRange !== range) closeDateRange(openRange, false);
        });

        const from = range.querySelector("[data-range-from]").value;
        const to = range.querySelector("[data-range-to]").value;
        const viewDate = parseRangeDate(from) || new Date();
        range.dataset.rangeMode = from && !to ? "end" : "start";
        range.dataset.viewYear = String(viewDate.getFullYear());
        range.dataset.viewMonth = String(viewDate.getMonth());
        range.dataset.focusDate = rangeDateValue(viewDate);
        renderDateRangeCalendar(range);
        range.querySelector(".date-range-popover").hidden = false;
        range.classList.add("is-open");
        range.querySelector("[data-range-toggle]").setAttribute("aria-expanded", "true");
        const focusedDay = range.querySelector("[data-range-days] button[tabindex='0']:not(:disabled)") ||
            range.querySelector("[data-range-days] button:not(:disabled)");
        if (focusedDay) focusedDay.focus();
    }

    document.addEventListener("click", function (event) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }

        const range = target.closest("[data-date-range]");
        const toggle = target.closest("[data-range-toggle]");
        if (toggle && range) {
            if (range.classList.contains("is-open")) {
                closeDateRange(range, false);
            } else {
                openDateRange(range);
            }
            return;
        }

        if (range) {
            const clear = target.closest("[data-range-clear]");
            if (clear) {
                range.querySelector("[data-range-from]").value = "";
                range.querySelector("[data-range-to]").value = "";
                range.dataset.rangeMode = "start";
                updateDateRangeDisplay(range);
                if (range.classList.contains("is-open")) {
                    renderDateRangeCalendar(range);
                }
                return;
            }

            const monthStep = target.closest("[data-range-month-step]");
            if (monthStep) {
                const month = new Date(
                    Number(range.dataset.viewYear),
                    Number(range.dataset.viewMonth) + Number(monthStep.dataset.rangeMonthStep),
                    1
                );
                range.dataset.viewYear = String(month.getFullYear());
                range.dataset.viewMonth = String(month.getMonth());
                renderDateRangeCalendar(range);
                range.querySelector(
                    '[data-range-month-step="' + monthStep.dataset.rangeMonthStep + '"]'
                ).focus();
                return;
            }

            const day = target.closest("[data-range-date]");
            if (day && !day.disabled) {
                const start = range.querySelector("[data-range-from]");
                const end = range.querySelector("[data-range-to]");
                if (range.dataset.rangeMode === "end") {
                    if (day.dataset.rangeDate < start.value) {
                        return;
                    }
                    end.value = day.dataset.rangeDate;
                    updateDateRangeDisplay(range);
                    renderDateRangeCalendar(range);
                    closeDateRange(range, true);
                } else {
                    start.value = day.dataset.rangeDate;
                    end.value = "";
                    range.dataset.rangeMode = "end";
                    range.dataset.focusDate = day.dataset.rangeDate;
                    updateDateRangeDisplay(range);
                    renderDateRangeCalendar(range);
                    const selectedStart = range.querySelector(
                        '[data-range-date="' + day.dataset.rangeDate + '"]'
                    );
                    if (selectedStart) selectedStart.focus();
                }
                return;
            }

            if (target.closest("[data-range-done]")) {
                closeDateRange(range, true);
                return;
            }
        }

        document.querySelectorAll("[data-date-range].is-open").forEach(function (openRange) {
            if (!openRange.contains(target)) closeDateRange(openRange, false);
        });
    });

    document.addEventListener("keydown", function (event) {
        const openRange = document.querySelector("[data-date-range].is-open");
        if (!openRange) {
            return;
        }
        if (event.key === "Escape") {
            event.stopPropagation();
            closeDateRange(openRange, true);
            return;
        }

        const focusedDay = event.target instanceof Element
            ? event.target.closest("[data-range-date]")
            : null;
        if (!focusedDay || !openRange.contains(focusedDay)) {
            return;
        }

        const currentDate = parseRangeDate(focusedDay.dataset.rangeDate);
        if (!currentDate) {
            return;
        }

        let nextDate = new Date(currentDate);
        if (event.key === "ArrowLeft") nextDate.setDate(nextDate.getDate() - 1);
        else if (event.key === "ArrowRight") nextDate.setDate(nextDate.getDate() + 1);
        else if (event.key === "ArrowUp") nextDate.setDate(nextDate.getDate() - 7);
        else if (event.key === "ArrowDown") nextDate.setDate(nextDate.getDate() + 7);
        else if (event.key === "Home") nextDate.setDate(nextDate.getDate() - nextDate.getDay());
        else if (event.key === "End") nextDate.setDate(nextDate.getDate() + (6 - nextDate.getDay()));
        else if (event.key === "PageUp" || event.key === "PageDown") {
            const dayOfMonth = nextDate.getDate();
            nextDate.setDate(1);
            nextDate.setMonth(nextDate.getMonth() + (event.key === "PageUp" ? -1 : 1));
            nextDate.setDate(Math.min(
                dayOfMonth,
                new Date(nextDate.getFullYear(), nextDate.getMonth() + 1, 0).getDate()
            ));
        }
        else return;

        event.preventDefault();
        focusDateRangeDay(openRange, rangeDateValue(nextDate));
        const nextFocusedDay = openRange.querySelector(
            '[data-range-date="' + rangeDateValue(nextDate) + '"]'
        );
        if (nextFocusedDay && nextFocusedDay.disabled) {
            focusDateRangeDay(openRange, openRange.querySelector("[data-range-from]").value);
        }
    });

    document.querySelectorAll("[data-date-range]").forEach(updateDateRangeDisplay);

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const requiredRange = form.querySelector("[data-date-range][data-range-required]");
        if (requiredRange) {
            const from = requiredRange.querySelector("[data-range-from]").value;
            const to = requiredRange.querySelector("[data-range-to]").value;
            const error = requiredRange.querySelector("[data-range-error]");
            const toggle = requiredRange.querySelector("[data-range-toggle]");
            if (!from || !to || to < from) {
                event.preventDefault();
                error.hidden = false;
                toggle.setAttribute("aria-invalid", "true");
                toggle.focus();
                return;
            }
            error.hidden = true;
            toggle.removeAttribute("aria-invalid");
        }

        if (!form.hasAttribute("data-search-form")) {
            return;
        }

        if (form.dataset.searchSubmitting === "true") {
            event.preventDefault();
            return;
        }

        form.dataset.searchSubmitting = "true";
        form.setAttribute("aria-busy", "true");
        const submitButton = event.submitter instanceof HTMLButtonElement &&
            event.submitter.matches("[data-search-submit]")
            ? event.submitter
            : form.querySelector("[data-search-submit]");
        if (submitButton) {
            submitButton.textContent = submitButton.classList.contains("search-submit")
                ? "Searching..."
                : "Applying...";
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

    document.addEventListener("click", function (event) {
        const printButton = event.target instanceof Element
            ? event.target.closest("[data-print-page]")
            : null;
        if (printButton) {
            window.print();
        }
    });

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

    document.querySelectorAll("[data-profile-picture-picker]").forEach(function (button) {
        const input = document.getElementById(
            button.getAttribute("data-profile-picture-picker")
        );
        if (!input) {
            return;
        }

        button.addEventListener("click", function () {
            input.click();
        });
        input.addEventListener("change", function () {
            const name = button.parentElement.querySelector("[data-profile-picture-name]");
            if (name) {
                name.textContent = input.files.length
                    ? input.files[0].name
                    : "No new photo selected";
            }
        });
    });

    if (menuToggle && sidebar) {
        menuToggle.addEventListener("click", function () {
            const isOpen = sidebar.classList.toggle("open");
            menuToggle.setAttribute("aria-expanded", String(isOpen));
        });

        document.addEventListener("click", function (event) {
            if (window.innerWidth > 800) {
                return;
            }
            const target = event.target;
            const selectedLink = target instanceof Element
                ? target.closest(".nav-links a")
                : null;
            if (
                selectedLink ||
                (!sidebar.contains(target) && !menuToggle.contains(target))
            ) {
                sidebar.classList.remove("open");
                menuToggle.setAttribute("aria-expanded", "false");
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && sidebar.classList.contains("open")) {
                sidebar.classList.remove("open");
                menuToggle.setAttribute("aria-expanded", "false");
                menuToggle.focus();
            }
        });
    }

    (function enableClientNavigation() {
        const main = document.querySelector("main.content");
        const mainArea = document.querySelector(".main-area");
        const navigation = document.querySelector(".nav-links");
        if (
            !main ||
            !mainArea ||
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
                main.querySelectorAll("[data-date-range]").forEach(updateDateRangeDisplay);
                main.setAttribute("aria-busy", "false");
                main.classList.remove("navigation-enter");
                window.requestAnimationFrame(function () {
                    main.classList.add("navigation-enter");
                    window.setTimeout(function () {
                        main.classList.remove("navigation-enter");
                    }, 240);
                });

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
                if (addHistory) mainArea.scrollTo(0, 0);
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
