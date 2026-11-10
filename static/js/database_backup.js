(function () {
    let pendingAction = null;

    function syncPasswordField(toggleId, fieldId, inputId) {
        const toggle = document.getElementById(toggleId);
        const field = document.getElementById(fieldId);
        const input = document.getElementById(inputId);
        if (!toggle || !field || !input) return;
        field.hidden = !toggle.checked;
        input.required = toggle.checked;
        if (!toggle.checked) input.value = "";
    }

    function initialize() {
        syncPasswordField("encryptBackup", "createPasswordField", "encryptionPassword");
        syncPasswordField("encryptedRestore", "restorePasswordField", "restorePassword");
    }

    function openConfirmation(nextAction, nextTitle, nextMessage, nextButtonLabel) {
        const dialog = document.getElementById("backupConfirmationDialog");
        if (!dialog) return;
        pendingAction = nextAction;
        document.getElementById("backupConfirmationTitle").textContent = nextTitle;
        document.getElementById("backupConfirmationMessage").textContent = nextMessage;
        dialog.querySelector("[data-backup-confirm]").textContent = nextButtonLabel;
        if (!dialog.open) dialog.showModal();
    }

    document.addEventListener("change", function (event) {
        if (
            event.target?.id === "encryptBackup" ||
            event.target?.id === "encryptedRestore"
        ) {
            initialize();
        }
    });

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        if (form.matches("[data-backup-delete]")) {
            event.preventDefault();
            openConfirmation(
                function () {
                    HTMLFormElement.prototype.submit.call(form);
                },
                "Delete this backup?",
                "This permanently removes the selected backup package and its history record.",
                "Delete backup"
            );
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
            openConfirmation(
                function () {
                    form.dataset.confirmed = "true";
                    form.elements.namedItem("confirmed_restore").value = "yes";
                    form.querySelector("button[type=submit]")?.classList.add("is-loading");
                    HTMLFormElement.prototype.submit.call(form);
                },
                "Replace the active database?",
                "All active tables will be dropped before this backup is restored. This cannot be undone.",
                "Replace database"
            );
            return;
        }

        if (form.matches("[data-backup-operation]")) {
            form.querySelector("button[type=submit]")?.classList.add("is-loading");
        }
    });

    document.addEventListener("click", function (event) {
        const dialog = document.getElementById("backupConfirmationDialog");
        if (!dialog) return;

        const confirmButton = event.target.closest("[data-backup-confirm]");
        if (confirmButton && dialog.contains(confirmButton)) {
            const action = pendingAction;
            pendingAction = null;
            dialog.close();
            if (action) action();
            return;
        }

        const cancelButton = event.target.closest("[data-backup-cancel]");
        if (cancelButton && dialog.contains(cancelButton)) {
            pendingAction = null;
            dialog.close();
            return;
        }

        if (event.target === dialog) {
            pendingAction = null;
            dialog.close();
        }
    });

    window.initializeDatabaseBackupPage = initialize;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
