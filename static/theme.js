// =====================================================
// VAULTSHARE GLOBAL THEME
// =====================================================

(function () {

    const savedTheme =
        localStorage.getItem("vaultshare-theme") || "dark";

    if (savedTheme === "light") {
        document.body.classList.add("light-mode");
    } else {
        document.body.classList.remove("light-mode");
    }

})();


// =====================================================
// GLOBAL NOTIFICATION SETTING
// =====================================================

(function () {

    const notifications =
        localStorage.getItem("vaultshare-notifications");

    if (notifications === "off") {
        document.body.classList.add("notifications-off");
    }

})();