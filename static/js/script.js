    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (window.lucide) {
        window.lucide.createIcons();
    }

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