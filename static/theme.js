(function () {
    try { localStorage.setItem("vaultshare-theme", "dark"); } catch (_) {}
    document.documentElement.dataset.theme = "dark";
    document.body.classList.remove("light-mode");
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => button.remove());
    let notifications = "on";
    try { notifications = localStorage.getItem("vaultshare-notifications") || "on"; } catch (_) {}
    document.body.classList.toggle("notifications-off", notifications === "off");
})();
