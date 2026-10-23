try {
  document.documentElement.dataset.theme =
    localStorage.getItem("autolabel.theme") || "light";
} catch {
  /* Private browsing can disable storage. */
}
