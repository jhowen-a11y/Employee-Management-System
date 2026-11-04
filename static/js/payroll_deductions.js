(function () {
    "use strict";

    const form = document.querySelector("[data-payroll-deduction-form]");
    if (!form) {
        return;
    }

    const employee = form.querySelector('[name="employee_id"]');
    const salary = form.querySelector('[name="basic_salary"]');
    const allowances = form.querySelector('[name="allowances"]');
    const range = form.querySelector("[data-date-range]");
    const periodStart = range && range.querySelector("[data-range-from]");
    const periodEnd = range && range.querySelector("[data-range-to]");
    const panel = form.querySelector("[data-payroll-preview]");
    const message = panel.querySelector("[data-preview-message]");
    const results = panel.querySelector("[data-preview-results]");
    const refresh = panel.querySelector("[data-preview-refresh]");
    let requestId = 0;
    let debounceTimer;

    function scheduleRefresh() {
        window.clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(refreshPreview, 250);
    }

    async function refreshPreview() {
        if (!employee.value || !periodStart.value || !periodEnd.value || !salary.value) {
            results.hidden = true;
            message.textContent = "Select an employee and pay period to calculate deductions.";
            return;
        }

        const thisRequest = ++requestId;
        const params = new URLSearchParams({
            employee_id: employee.value,
            pay_period_start: periodStart.value,
            pay_period_end: periodEnd.value,
            basic_salary: salary.value,
            allowances: allowances.value || "0"
        });
        message.textContent = "Calculating attendance deductions…";
        refresh.disabled = true;

        try {
            const response = await fetch(form.dataset.previewUrl + "?" + params, {
                headers: { Accept: "application/json" },
                cache: "no-store"
            });
            const payload = await response.json();
            if (thisRequest !== requestId) {
                return;
            }
            if (!response.ok) {
                throw new Error(payload.error || "Unable to calculate deductions.");
            }

            panel.querySelectorAll("[data-preview-value]").forEach((element) => {
                const key = element.dataset.previewValue;
                element.textContent = payload[key];
                if (key.includes("deduction") || key === "estimated_net_pay" ||
                    key === "daily_rate" || key === "hourly_rate") {
                    element.textContent = new Intl.NumberFormat(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    }).format(Number(payload[key]));
                }
            });
            results.hidden = false;
            message.textContent = payload.incomplete_attendance_days
                ? payload.incomplete_attendance_days +
                  " incomplete or conflicting attendance day(s) were not deducted."
                : "Preview is based on attendance records currently saved.";
        } catch (error) {
            if (thisRequest === requestId) {
                results.hidden = true;
                message.textContent = error.message || "Unable to calculate deductions.";
            }
        } finally {
            if (thisRequest === requestId) {
                refresh.disabled = false;
            }
        }
    }

    employee.addEventListener("change", function () {
        const selected = employee.selectedOptions[0];
        if (selected && selected.dataset.salary) {
            salary.value = selected.dataset.salary;
        }
        scheduleRefresh();
    });
    salary.addEventListener("input", scheduleRefresh);
    allowances.addEventListener("input", scheduleRefresh);
    if (range) {
        range.addEventListener("rangechange", scheduleRefresh);
    }
    refresh.addEventListener("click", refreshPreview);

    if (!salary.value && employee.value) {
        const selected = employee.selectedOptions[0];
        if (selected && selected.dataset.salary) {
            salary.value = selected.dataset.salary;
        }
    }
    scheduleRefresh();
})();
