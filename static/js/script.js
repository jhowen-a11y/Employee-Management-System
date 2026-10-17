    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (window.lucide) {
        window.lucide.createIcons();
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