(function () {
  var workerCode = 'setInterval(function () { postMessage("ping"); }, 20000);';
  var blob = new Blob([workerCode], { type: "application/javascript" });
  var worker = new Worker(URL.createObjectURL(blob));

  worker.onmessage = function () {
    fetch(window.location.href, { method: "HEAD", cache: "no-store" }).catch(
      function () {}
    );
  };

  document.addEventListener("shiny:disconnected", function () {
    setTimeout(function () {
      window.location.reload();
    }, 2000);
  });
})();
