(function () {
    const encryptToggle = document.getElementById("encryptBackup");
    const createPasswordField = document.getElementById("createPasswordField");
    const encryptionPassword = document.getElementById("encryptionPassword");
    const encryptedRestore = document.getElementById("encryptedRestore");
    const restorePasswordField = document.getElementById("restorePasswordField");
    const restorePassword = document.getElementById("restorePassword");
    const dialog = document.getElementById("backupConfirmationDialog");

    if (!dialog) return;

    function syncPasswordField(toggle, field, input) {
        if (!toggle || !field || !input) return;
        field.hidden = !toggle.checked;
        input.required = toggle.checked;
        if (!toggle.checked) input.value = "";
    }

    encryptToggle?.addEventListener("change", function () {
        syncPasswordField(encryptToggle, createPasswordField, encryptionPassword);
    });

    encryptedRestore?.addEventListener("change", function () {
        syncPasswordField(encryptedRestore, restorePasswordField, restorePassword);
    });

    const title = document.getElementById("backupConfirmationTitle");
    const message = document.getElementById("backupConfirmationMessage");
    const confirmButton = dialog.querySelector("[data-backup-confirm]");
    const cancelButton = dialog.querySelector("[data-backup-cancel]");
    let pendingAction = null;

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        if (form.matches("[data-backup-delete]")) {
            event.preventDefault();
            pendingAction = function () {
                HTMLFormElement.prototype.submit.call(form);
            };
            title.textContent = "Delete this backup?";
            message.textContent =
                "This permanently removes the selected backup package and its history record.";
            confirmButton.textContent = "Delete backup";
            dialog.showModal();
            return;
        }

        if (form.matches("[data-backup-restore]")) {
            const confirmation = form.elements.namedItem("confirm_overwrite");
            if (!confirmation || !confirmation.checked) {
                event.preventDefault();
                return;
            }
            if (form.dataset.confirmed === "true") {
                form.querySelector("button[type=submit]")?.classList.add("is-loading");
                return;
            }
            event.preventDefault();
            pendingAction = function () {
                form.dataset.confirmed = "true";
                form.elements.namedItem("confirmed_restore").value = "yes";
                form.querySelector("button[type=submit]")?.classList.add("is-loading");
                HTMLFormElement.prototype.submit.call(form);
            };
            title.textContent = "Restore to a new database?";
            message.textContent =
                "A new database will be created and populated. The active database will not be changed.";
            confirmButton.textContent = "Restore backup";
            dialog.showModal();
            return;
        }

        if (form.matches("[data-backup-operation]")) {
            form.querySelector("button[type=submit]")?.classList.add("is-loading");
        }
    });

    confirmButton.addEventListener("click", function () {
        const action = pendingAction;
        pendingAction = null;
        dialog.close();
        if (action) action();
    });

    cancelButton.addEventListener("click", function () {
        pendingAction = null;
        dialog.close();
    });

    dialog.addEventListener("click", function (event) {
        if (event.target === dialog) {
            pendingAction = null;
            dialog.close();
        }
    });

    const jobsPanel = document.getElementById("backupJobStatus");
    const jobRows = document.getElementById("backupJobRows");
    if (!jobsPanel || !jobRows) return;

    function renderJobs(jobs) {
        jobRows.replaceChildren();
        if (!jobs.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "No recent worker operations.";
            row.appendChild(cell);
            jobRows.appendChild(row);
            return;
        }

        jobs.forEach(function (job) {
            const row = document.createElement("tr");
            const idCell = document.createElement("td");
            const id = document.createElement("code");
            id.textContent = String(job.id || "").slice(0, 8);
            idCell.appendChild(id);
            row.appendChild(idCell);

            [job.operation, job.created_at].forEach(function (value) {
                const cell = document.createElement("td");
                cell.textContent = value || "";
                row.appendChild(cell);
            });

            const statusCell = document.createElement("td");
            const status = document.createElement("span");
            status.className = "database-backup-status is-" + String(job.status || "failed");
            status.textContent = job.status || "Unknown";
            statusCell.appendChild(status);
            row.appendChild(statusCell);

            const messageCell = document.createElement("td");
            messageCell.textContent = job.message || "";
            row.appendChild(messageCell);
            jobRows.appendChild(row);
        });
    }

    function refreshJobs() {
        fetch(jobsPanel.dataset.jobsUrl, {
            credentials: "same-origin",
            cache: "no-store",
            headers: { Accept: "application/json" }
        })
            .then(function (response) {
                if (!response.ok) throw new Error("Backup job status is unavailable.");
                return response.json();
            })
            .then(function (payload) {
                const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
                renderJobs(jobs);
                if (jobs.some(function (job) {
                    return job.status === "queued" || job.status === "running";
                })) {
                    window.setTimeout(refreshJobs, 3000);
                }
            })
            .catch(function () {
                const row = document.createElement("tr");
                const cell = document.createElement("td");
                cell.colSpan = 5;
                cell.textContent = "Worker status could not be refreshed. Reload the page to try again.";
                row.appendChild(cell);
                jobRows.replaceChildren(row);
            });
    }

    window.setTimeout(refreshJobs, 1500);
})();
