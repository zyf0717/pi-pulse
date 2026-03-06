(function () {
  function findMetricCardTrigger(node) {
    while (node) {
      if (node.classList && node.classList.contains("metric-card-trigger")) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function activateMetricCard(node) {
    var targetId = node.getAttribute("data-chart-target");
    var nextValue = node.getAttribute("data-chart-value");
    var select = document.getElementById(targetId);
    if (!select || select.value === nextValue) {
      return;
    }
    select.value = nextValue;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  document.addEventListener("click", function (event) {
    var trigger = findMetricCardTrigger(event.target);
    if (!trigger) {
      return;
    }
    activateMetricCard(trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    var trigger = findMetricCardTrigger(event.target);
    if (!trigger) {
      return;
    }
    event.preventDefault();
    activateMetricCard(trigger);
  });
})();
