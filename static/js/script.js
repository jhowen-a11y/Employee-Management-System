    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (window.lucide) {
        window.lucide.createIcons();
    }

    document.addEventListener("input", function (event) {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.hasAttribute("data-uppercase")) {
            return;
        }

        const start = input.selectionStart;
        const end = input.selectionEnd;
        input.value = input.value.toUpperCase();
        if (start !== null && end !== null) {
            input.setSelectionRange(start, end);
        }
    });

    function roleChartControl(target) {
        return target instanceof Element
            ? target.closest(".admin-role-chart [data-role]")
            : null;
    }

    function setRoleChartHighlight(chart, role) {
        if (role) {
            chart.dataset.activeRole = role;
        } else {
            delete chart.dataset.activeRole;
        }
    }

    document.addEventListener("pointerover", function (event) {
        const control = roleChartControl(event.target);
        if (!control) return;
        setRoleChartHighlight(control.closest(".admin-role-chart"), control.dataset.role);
    });

    document.addEventListener("pointerout", function (event) {
        const control = roleChartControl(event.target);
        if (!control) return;
        const chart = control.closest(".admin-role-chart");
        const nextControl = roleChartControl(event.relatedTarget);
        if (nextControl && nextControl.closest(".admin-role-chart") === chart) {
            setRoleChartHighlight(chart, nextControl.dataset.role);
            return;
        }
        const focusedControl = roleChartControl(document.activeElement);
        setRoleChartHighlight(
            chart,
            focusedControl && focusedControl.closest(".admin-role-chart") === chart
                ? focusedControl.dataset.role
                : null
        );
    });

    document.addEventListener("focusin", function (event) {
        const control = roleChartControl(event.target);
        if (!control) return;
        setRoleChartHighlight(control.closest(".admin-role-chart"), control.dataset.role);
    });

    document.addEventListener("focusout", function (event) {
        const control = roleChartControl(event.target);
        if (!control) return;
        const chart = control.closest(".admin-role-chart");
        const nextControl = roleChartControl(event.relatedTarget);
        if (nextControl && nextControl.closest(".admin-role-chart") === chart) {
            setRoleChartHighlight(chart, nextControl.dataset.role);
            return;
        }
        const hoveredControl = roleChartControl(
            chart.querySelector(":hover")
        );
        setRoleChartHighlight(
            chart,
            hoveredControl ? hoveredControl.dataset.role : null
        );
    });

    document.addEventListener("click", function (event) {
        const toggle = event.target instanceof Element
            ? event.target.closest("[data-email-toggle]")
            : null;
        if (!toggle) return;

        const email = toggle.closest(".user-email-display")
            ?.querySelector("[data-email]");
        if (!email) return;

        const isVisible = toggle.getAttribute("aria-expanded") !== "true";
        email.textContent = isVisible ? email.dataset.email : email.dataset.maskedEmail;
        toggle.setAttribute("aria-expanded", String(isVisible));
        toggle.setAttribute("aria-label", isVisible ? "Hide email" : "Show email");
        toggle.title = isVisible ? "Hide email" : "Show email";
        toggle.innerHTML = '<i data-lucide="' +
            (isVisible ? "eye-off" : "eye") + '" aria-hidden="true"></i>';
        if (window.lucide) window.lucide.createIcons();
    });

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

    const confirmationDialog = document.getElementById("actionConfirmationDialog");
    const confirmationTitle = document.getElementById("actionConfirmationTitle");
    const confirmationMessage = document.getElementById("actionConfirmationMessage");
    const confirmationContext = document.getElementById("actionConfirmationContext");
    const confirmationIcon = document.getElementById("actionConfirmationIcon");
    const confirmationReason = document.getElementById("actionConfirmationReason");
    const confirmationReasonInput = document.getElementById("actionConfirmationReasonInput");
    const confirmationError = document.getElementById("actionConfirmationError");
    const cancelConfirmation = document.getElementById("cancelActionConfirmation");
    const closeConfirmation = document.getElementById("closeActionConfirmation");
    const confirmAction = document.getElementById("confirmActionConfirmation");
    let pendingAction = null;
    let confirmationBusy = false;
    let confirmedDeleteForm = null;
    let confirmedModalDeleteForm = null;
    let confirmedReviewForm = null;
    let resolveModalAction = null;

    function setConfirmationButton(icon, label) {
        confirmAction.innerHTML =
            '<i data-lucide="' + icon + '" aria-hidden="true"></i><span></span>';
        confirmAction.querySelector("span").textContent = label;
        if (window.lucide) window.lucide.createIcons();
    }

    function clearConfirmationReason(form) {
        if (!form) return;
        form.dataset.deleteReasonReady = "false";
        const reasonField = form.querySelector('input[name="reason"]');
        if (reasonField) reasonField.value = "";
    }

    function closeActionConfirmation() {
        if (confirmationBusy) return;
        if (pendingAction?.form?.hasAttribute("data-delete-reason")) {
            clearConfirmationReason(pendingAction.form);
        }
        pendingAction = null;
        confirmationError.hidden = true;
        confirmationError.textContent = "";
        confirmationReasonInput.value = "";
        confirmationReason.hidden = true;
        if (confirmationDialog.open) confirmationDialog.close();
    }

    function showActionConfirmation(options, action) {
        if (!confirmationDialog || !confirmationTitle || !confirmationMessage ||
            !confirmAction || !cancelConfirmation) {
            throw new Error("The shared action confirmation dialog is unavailable.");
        }
        if (confirmationBusy) return;

        action.options = options;
        pendingAction = action;
        confirmationBusy = false;
        confirmAction.disabled = false;
        cancelConfirmation.disabled = false;
        closeConfirmation.disabled = false;
        confirmAction.removeAttribute("aria-busy");
        confirmationTitle.textContent = options.title;
        confirmationMessage.textContent = options.message;
        confirmationContext.textContent = options.context || "";
        confirmationContext.hidden = !options.context;
        confirmationDialog.setAttribute(
            "aria-describedby",
            options.context
                ? "actionConfirmationMessage actionConfirmationContext"
                : "actionConfirmationMessage"
        );
        confirmationDialog.dataset.variant = options.variant || "primary";
        confirmationIcon.innerHTML = '<i data-lucide="' +
            (options.icon || "triangle-alert") + '" aria-hidden="true"></i>';
        confirmAction.className = "button " +
            (options.variant === "danger" ? "button-danger" : "button-primary");
        setConfirmationButton(options.icon || "check", options.confirmText || "Confirm");
        cancelConfirmation.textContent = options.cancelText || "Cancel";
        confirmationReason.hidden = !action.requiresReason;
        confirmationReasonInput.value = "";
        confirmationError.hidden = true;
        confirmationError.textContent = "";
        if (window.lucide) window.lucide.createIcons();
        if (!confirmationDialog.open) {
            if (typeof confirmationDialog.showModal === "function") {
                confirmationDialog.showModal();
            } else {
                confirmationDialog.setAttribute("open", "");
            }
        }
        cancelConfirmation.focus();
    }

    function finishModalAction(result) {
        if (!resolveModalAction) return;
        const resolve = resolveModalAction;
        resolveModalAction = null;
        resolve(result);
    }

    document.addEventListener("click", function (event) {
        const printButton = event.target instanceof Element
            ? event.target.closest("[data-print-page]")
            : null;
        if (printButton) {
            window.print();
        }
    });

    if (confirmationDialog && confirmAction && confirmationReasonInput) {
        document.addEventListener("submit", function (event) {
            const form = event.target;
            if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm-delete")) {
                return;
            }

            if (confirmedDeleteForm === form) {
                confirmedDeleteForm = null;
                confirmedModalDeleteForm = form.closest("#recordModal")
                    ? form
                    : null;
                return;
            }

            event.preventDefault();
            showActionConfirmation({
                title: form.dataset.deleteTitle || "Delete this record?",
                message: form.dataset.deleteMessage || "This action cannot be undone.",
                confirmText: "Delete permanently",
                cancelText: "Cancel",
                variant: "danger",
                icon: "trash-2"
            }, {
                form: form,
                requiresReason: form.hasAttribute("data-delete-reason"),
                onConfirm: function () {
                    if (form.hasAttribute("data-delete-reason")) {
                        const reason = confirmationReasonInput.value.trim();
                        if (reason.length < 10 || reason.length > 1000) {
                            confirmationError.textContent =
                                "Enter a reason between 10 and 1000 characters.";
                            confirmationError.hidden = false;
                            confirmationReasonInput.focus();
                            return { success: false, validation: true };
                        }
                        const reasonField = form.querySelector('input[name="reason"]');
                        if (!reasonField) {
                            throw new Error("The attendance deletion form is missing its reason field.");
                        }
                        reasonField.value = reason;
                        form.dataset.deleteReasonReady = "true";
                    }

                    confirmedDeleteForm = form;
                    if (form.closest("#recordModal")) {
                        return new Promise(function (resolve) {
                            resolveModalAction = resolve;
                            form.requestSubmit();
                        });
                    }
                    form.requestSubmit();
                    return { success: true };
                }
            });
        });

        cancelConfirmation.addEventListener("click", closeActionConfirmation);
        closeConfirmation.addEventListener("click", closeActionConfirmation);

        confirmationDialog.addEventListener("cancel", function (event) {
            if (confirmationBusy) {
                event.preventDefault();
                return;
            }
            if (pendingAction?.form?.hasAttribute("data-delete-reason")) {
                clearConfirmationReason(pendingAction.form);
            }
            pendingAction = null;
            confirmationError.hidden = true;
        });

        confirmationDialog.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && !confirmationBusy) {
                event.preventDefault();
                closeActionConfirmation();
            }
        });

        confirmAction.addEventListener("click", async function () {
            if (!pendingAction || confirmationBusy) return;
            const action = pendingAction;
            confirmationBusy = true;
            confirmAction.disabled = true;
            confirmAction.setAttribute("aria-busy", "true");
            cancelConfirmation.disabled = true;
            closeConfirmation.disabled = true;
            setConfirmationButton("loader-circle", "Processing...");
            const spinner = confirmAction.querySelector("svg, i");
            if (spinner) spinner.classList.add("confirmation-spinner");

            let result;
            try {
                result = await action.onConfirm();
            } catch (error) {
                console.error("Confirmed action could not be completed:", error);
                result = {
                    success: false,
                    message: "The action could not be completed. Please try again."
                };
            }

            if (result?.success) {
                if (action.form?.hasAttribute("data-delete-reason")) {
                    action.form.dataset.deleteReasonReady = "false";
                }
                pendingAction = null;
                confirmationBusy = false;
                confirmAction.disabled = false;
                confirmAction.removeAttribute("aria-busy");
                cancelConfirmation.disabled = false;
                closeConfirmation.disabled = false;
                confirmationDialog.close();
                return;
            }

            confirmationBusy = false;
            confirmAction.disabled = false;
            confirmAction.removeAttribute("aria-busy");
            cancelConfirmation.disabled = false;
            closeConfirmation.disabled = false;
            confirmAction.className = "button " +
                (action.options.variant === "danger" ? "button-danger" : "button-primary");
            setConfirmationButton(
                action.options.icon || "check",
                action.options.confirmText || "Confirm"
            );
            if (result?.validation) {
                return;
            }
            confirmationError.textContent = result?.message ||
                "The action could not be completed. Please try again.";
            confirmationError.hidden = false;
        });
    }

    (function enableRecordModal() {
        const modal = document.getElementById("recordModal");
        const modalTitle = document.getElementById("recordModalTitle");
        const modalContent = document.getElementById("recordModalContent");
        const closeButton = document.getElementById("closeRecordModal");
        const main = document.querySelector("main.content");
        const mainArea = document.querySelector(".main-area");
        if (!modal || !modalTitle || !modalContent || !closeButton || !main) {
            return;
        }

        let returnFocus = null;
        let modalUrl = null;
        let modalRequest = null;
        let closeTimer = null;
        let priorBodyOverflow = "";
        let isSubmitting = false;

        function showMessage(title, message, retryUrl) {
            const state = document.createElement("div");
            state.className = "record-modal-message";
            state.setAttribute("role", retryUrl ? "alert" : "status");
            const heading = document.createElement("strong");
            heading.textContent = title;
            const description = document.createElement("p");
            description.textContent = message;
            state.append(heading, description);
            if (retryUrl) {
                const retry = document.createElement("button");
                retry.className = "button button-primary";
                retry.type = "button";
                retry.dataset.modalRetry = retryUrl;
                retry.textContent = "Try again";
                state.append(retry);
            }
            modalContent.replaceChildren(state);
            modalContent.setAttribute("aria-busy", "false");
        }

        function showPage(page, fallbackTitle, sourceUrl) {
            const pageMain = page.querySelector("main.content");
            if (!pageMain) {
                throw new Error("The requested record page did not contain its content.");
            }
            if (sourceUrl) {
                pageMain.querySelectorAll("form:not([action])").forEach(function (form) {
                    form.setAttribute("action", sourceUrl);
                });
            }
            const heading = pageMain.querySelector("h1");
            modalTitle.textContent = heading && heading.textContent.trim()
                ? heading.textContent.trim()
                : fallbackTitle;
            modalContent.replaceChildren(
                ...Array.from(pageMain.childNodes, function (node) {
                    return node.cloneNode(true);
                })
            );
            modalContent.setAttribute("aria-busy", "false");
            updateModalRoleFields();
            if (window.lucide) window.lucide.createIcons();
        }

        function updateModalRoleFields() {
            const roleSelect = modalContent.querySelector("#role");
            const employeeFields = modalContent.querySelector("#employeeFields");
            if (!roleSelect || !employeeFields) return;

            const isEmployee = roleSelect.value === "employee";
            employeeFields.hidden = !isEmployee;
            employeeFields.querySelectorAll("input, select").forEach(function (input) {
                input.required = isEmployee;
            });
        }

        function hasUnsavedChanges() {
            return modal.dataset.dirty === "true";
        }

        function confirmDiscardChanges(onDiscard) {
            showActionConfirmation({
                title: "Discard unsaved changes?",
                message: "You have unsaved changes. Discard them and close this window?",
                confirmText: "Discard changes",
                cancelText: "Continue editing",
                variant: "danger",
                icon: "triangle-alert"
            }, {
                onConfirm: function () {
                    modal.dataset.dirty = "false";
                    onDiscard();
                    return { success: true };
                }
            });
        }

        async function loadRecord(url) {
            modalUrl = url.href;
            modal.dataset.dirty = "false";
            if (modalRequest) modalRequest.abort();
            const controller = new AbortController();
            modalRequest = controller;
            let timedOut = false;
            const timeoutId = window.setTimeout(function () {
                timedOut = true;
                controller.abort();
            }, 15000);
            let errorTitle = "Unable to load this record";
            let errorMessage = "The service could not load this record. Please try again.";
            let retryUrl = url.href;
            modalTitle.textContent = "Loading record";
            modalContent.setAttribute("aria-busy", "true");
            showMessage("Loading record details", "Please wait…", null);
            modalContent.setAttribute("aria-busy", "true");

            try {
                const response = await window.fetch(url.href, {
                    method: "GET",
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    signal: controller.signal
                });
                const destination = new URL(response.url || url.href);
                if (destination.pathname === "/login") {
                    window.location.assign(destination.href);
                    return;
                }
                if (!response.ok) {
                    if (response.status === 403) {
                        errorTitle = "Access denied";
                        errorMessage = "You do not have permission to view this record.";
                        retryUrl = null;
                    } else if (response.status === 404) {
                        errorTitle = "Record not found";
                        errorMessage = "This record may have been removed or is unavailable.";
                        retryUrl = null;
                    } else if (response.status >= 500) {
                        errorTitle = "Service temporarily unavailable";
                        errorMessage = "Please check your connection and try again.";
                    } else {
                        errorMessage = "The request could not be completed. Please try again.";
                        retryUrl = null;
                    }
                    throw new Error("The record could not be loaded (HTTP " + response.status + ").");
                }
                const page = new DOMParser().parseFromString(
                    await response.text(),
                    "text/html"
                );
                showPage(page, "Record details", url.href);
            } catch (error) {
                if (controller.signal.aborted && !timedOut) return;
                if (timedOut) {
                    errorTitle = "Request timed out";
                    errorMessage = "The record is taking too long to load. Please try again.";
                }
                console.error("Record details could not be loaded:", error);
                showMessage(errorTitle, errorMessage, retryUrl);
            } finally {
                window.clearTimeout(timeoutId);
                if (modalRequest === controller) modalRequest = null;
            }
        }

        function closeModal(immediate) {
            if (!modal.open) return;
            if (hasUnsavedChanges()) {
                confirmDiscardChanges(function () {
                    closeModal(immediate);
                });
                return;
            }
            window.clearTimeout(closeTimer);
            modal.classList.add("is-closing");
            const reducedMotion = window.matchMedia &&
                window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            if (immediate || reducedMotion) {
                modal.close();
                return;
            }
            closeTimer = window.setTimeout(function () {
                if (modal.open) modal.close();
            }, 190);
        }

        function openModal(trigger, url, size) {
            if (modal.open && hasUnsavedChanges()) {
                confirmDiscardChanges(function () {
                    openModal(trigger, url, size);
                });
                return;
            }
            window.clearTimeout(closeTimer);
            modal.classList.remove("is-closing");
            modal.dataset.modalSize = size || "standard";
            if (!modal.open) {
                returnFocus = trigger;
                priorBodyOverflow = document.body.style.overflow;
                document.body.style.overflow = "hidden";
                if (typeof modal.showModal !== "function") {
                    window.location.assign(url.href);
                    return;
                }
                modal.showModal();
                closeButton.focus();
            }
            loadRecord(url);
        }

        modal.addEventListener("close", function () {
            window.clearTimeout(closeTimer);
            modal.classList.remove("is-closing");
            document.body.style.overflow = priorBodyOverflow;
            if (modalRequest) {
                modalRequest.abort();
                modalRequest = null;
            }
            modalUrl = null;
            if (returnFocus && returnFocus.isConnected) {
                returnFocus.focus();
            } else {
                const fallbackFocus = main.querySelector("h1");
                if (fallbackFocus) {
                    fallbackFocus.tabIndex = -1;
                    fallbackFocus.focus();
                }
            }
            returnFocus = null;
        });

        modal.addEventListener("cancel", function (event) {
            event.preventDefault();
            closeModal(false);
        });

        modal.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                event.preventDefault();
                closeModal(false);
            }
        });

        closeButton.addEventListener("click", function () {
            closeModal(false);
        });

        modal.addEventListener("click", function (event) {
            if (event.target === modal) closeModal(false);
        });

        modalContent.addEventListener("input", function (event) {
            if (event.target instanceof HTMLElement &&
                event.target.closest("form")) {
                modal.dataset.dirty = "true";
            }
        });

        modalContent.addEventListener("change", function (event) {
            if (!(event.target instanceof HTMLElement)) return;
            if (event.target.matches("#role")) updateModalRoleFields();
            if (event.target.closest("form")) modal.dataset.dirty = "true";

            if (event.target.matches("[data-profile-picture-input]")) {
                const picker = modalContent.querySelector("[data-profile-picture-name]");
                if (picker) {
                    picker.textContent = event.target.files.length
                        ? event.target.files[0].name
                        : "No new photo selected";
                }
            }
        });

        modalContent.addEventListener("click", function (event) {
            const target = event.target instanceof Element ? event.target : null;
            if (!target) return;
            const passwordToggle = target.closest("[data-password-toggle]");
            if (passwordToggle) {
                const password = modalContent.querySelector(
                    "#" + CSS.escape(passwordToggle.getAttribute("aria-controls"))
                );
                if (!password) return;
                const isVisible = password.type === "text";
                password.type = isVisible ? "password" : "text";
                passwordToggle.innerHTML =
                    '<i data-lucide="' + (isVisible ? "eye-off" : "eye") + '" aria-hidden="true"></i>';
                passwordToggle.setAttribute(
                    "aria-label",
                    isVisible ? "Show password" : "Hide password"
                );
                passwordToggle.setAttribute("aria-pressed", String(!isVisible));
                if (window.lucide) window.lucide.createIcons();
                return;
            }

            const photoPicker = target.closest("[data-profile-picture-picker]");
            if (photoPicker) {
                const input = modalContent.querySelector(
                    "#" + CSS.escape(photoPicker.dataset.profilePicturePicker)
                );
                if (input) input.click();
            }
        });

        modal.addEventListener("keydown", function (event) {
            if (event.key !== "Tab") return;
            const focusable = Array.from(modal.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )).filter(function (element) {
                return !element.hidden && element.getClientRects().length > 0;
            });
            if (!focusable.length) {
                event.preventDefault();
                closeButton.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });

        document.addEventListener("click", function (event) {
            if (event.defaultPrevented || event.button !== 0 ||
                event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
            }
            const target = event.target instanceof Element ? event.target : null;
            if (!target) return;

            const retry = target.closest("[data-modal-retry]");
            if (retry) {
                event.preventDefault();
                const retryUrl = new URL(retry.dataset.modalRetry, window.location.href);
                if (hasUnsavedChanges()) {
                    confirmDiscardChanges(function () {
                        loadRecord(retryUrl);
                    });
                    return;
                }
                loadRecord(retryUrl);
                return;
            }

            const link = target.closest("a");
            if (!link || link.hasAttribute("target") || link.hasAttribute("download")) return;
            if (link.hasAttribute("data-record-modal")) {
                const url = new URL(
                    link.getAttribute("href") || link.href,
                    window.location.href
                );
                if (url.origin === window.location.origin) {
                    event.preventDefault();
                    openModal(link, url, link.dataset.modalSize);
                }
                return;
            }
            if (modal.open && modal.contains(link) && link.hasAttribute("data-modal-close")) {
                event.preventDefault();
                closeModal(false);
                return;
            }
            if (modal.open && modal.contains(link)) {
                if (hasUnsavedChanges()) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    confirmDiscardChanges(function () {
                        closeModal(false);
                        window.location.assign(link.href);
                    });
                    return;
                }
                closeModal(false);
            }
        });

        async function refreshCurrentPage() {
            const currentScrollTop = mainArea ? mainArea.scrollTop : 0;
            const currentScrollY = window.scrollY;
            const response = await window.fetch(window.location.href, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok) {
                throw new Error("The current list could not be refreshed (HTTP " + response.status + ").");
            }
            const page = new DOMParser().parseFromString(await response.text(), "text/html");
            const pageMain = page.querySelector("main.content");
            if (!pageMain) throw new Error("The refreshed page did not contain its content.");
            main.innerHTML = pageMain.innerHTML;
            main.setAttribute("aria-busy", "false");
            if (mainArea) mainArea.scrollTop = currentScrollTop;
            window.scrollTo(window.scrollX, currentScrollY);
            if (window.lucide) window.lucide.createIcons();
        }

        document.addEventListener("submit", async function (event) {
            const form = event.target;
            if (!(form instanceof HTMLFormElement) || !modal.contains(form)) return;
            if (
                form.hasAttribute("data-confirm-delete") &&
                confirmedModalDeleteForm !== form
            ) {
                return;
            }
            const submitter = event.submitter instanceof HTMLButtonElement
                ? event.submitter
                : null;
            const reviewDecision = submitter?.dataset.reviewDecision;
            if (
                form.hasAttribute("data-leave-review") &&
                reviewDecision &&
                confirmedReviewForm !== form
            ) {
                event.preventDefault();
                const decision = reviewDecision.toLowerCase();
                const employeeName = modalContent.querySelector(
                    ".record-person-copy h2"
                )?.textContent.trim();
                const leaveType = Array.from(
                    modalContent.querySelectorAll(".record-detail-field")
                ).find(function (field) {
                    return field.querySelector("dt")?.textContent.trim() === "Leave type";
                })?.querySelector("dd")?.textContent.trim();
                showActionConfirmation({
                    title: decision === "decline"
                        ? "Decline leave request?"
                        : "Approve leave request?",
                    message: decision === "decline"
                        ? "Are you sure you want to decline this leave request?"
                        : "Are you sure you want to approve this leave request?",
                    context: [employeeName, leaveType].filter(Boolean).join(" · "),
                    confirmText: decision === "decline"
                        ? "Confirm decline"
                        : "Confirm approval",
                    cancelText: "Cancel",
                    variant: decision === "decline" ? "danger" : "primary",
                    icon: decision === "decline" ? "x" : "check"
                }, {
                    form: form,
                    submitter: submitter,
                    onConfirm: function () {
                        return new Promise(function (resolve) {
                            resolveModalAction = resolve;
                            confirmedReviewForm = form;
                            if (submitter) {
                                form.requestSubmit(submitter);
                            } else {
                                form.requestSubmit();
                            }
                        });
                    }
                });
                return;
            }
            if (confirmedReviewForm === form) confirmedReviewForm = null;
            if (confirmedModalDeleteForm === form) {
                confirmedModalDeleteForm = null;
            }
            event.preventDefault();
            if (isSubmitting) return;
            isSubmitting = true;
            modalContent.setAttribute("aria-busy", "true");
            const formData = new FormData(form);
            if (submitter instanceof HTMLButtonElement && submitter.name) {
                formData.append(submitter.name, submitter.value);
            }
            const submitButtons = Array.from(form.querySelectorAll(
                'button[type="submit"], button:not([type])'
            ));
            submitButtons.forEach(function (button) {
                button.disabled = true;
            });

            try {
                const response = await window.fetch(form.action || modalUrl, {
                    method: (form.method || "POST").toUpperCase(),
                    credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    body: formData
                });
                const resultUrl = new URL(response.url || modalUrl, window.location.href);
                if (resultUrl.pathname === "/login") {
                    window.location.assign(resultUrl.href);
                    return;
                }
                if (!response.ok) {
                    throw new Error("The action could not be completed (HTTP " + response.status + ").");
                }
                const resultPage = new DOMParser().parseFromString(
                    await response.text(),
                    "text/html"
                );
                const resultFlashes = resultPage.querySelector(
                    "main.content .flash-messages"
                );
                await refreshCurrentPage();
                if (modalUrl && resultUrl.pathname === new URL(modalUrl).pathname) {
                    showPage(resultPage, "Record details", modalUrl);
                } else {
                    if (resultFlashes && main) {
                        main.prepend(resultFlashes.cloneNode(true));
                    }
                    modal.dataset.dirty = "false";
                    closeModal(false);
                }
                finishModalAction({ success: true });
            } catch (error) {
                console.error("Record action could not be completed:", error);
                const statusMatch = /HTTP (\d+)/.exec(error.message);
                const status = statusMatch ? Number(statusMatch[1]) : null;
                let message = "Please try again. If the problem continues, reload the page.";
                if (status === 403) {
                    message = "You do not have permission to review this request.";
                } else if (status === 404) {
                    message = "This leave request is no longer available.";
                } else if (status === 409) {
                    message = "This request has already been reviewed. Reload its details to see the latest status.";
                } else if (status >= 500) {
                    message = "The service could not save this decision. Please try again.";
                }
                if (
                    form.hasAttribute("data-leave-review") ||
                    form.hasAttribute("data-confirm-delete")
                ) {
                    finishModalAction({ success: false, message: message });
                } else {
                    showMessage(
                        "Unable to complete this action",
                        message,
                        modalUrl
                    );
                }
            } finally {
                submitButtons.forEach(function (button) {
                    button.disabled = false;
                });
                modalContent.setAttribute("aria-busy", "false");
                isSubmitting = false;
            }
        });
    })();

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
                link.hasAttribute("target") ||
                link.hasAttribute("download") ||
                link.relList.contains("external")
            ) {
                return;
            }

            const url = new URL(
                link.getAttribute("href") || link.href,
                window.location.href
            );
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
