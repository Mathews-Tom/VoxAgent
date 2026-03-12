(function() {
  var config = document.currentScript.dataset;
  var iframe = document.createElement("iframe");
  iframe.src = (config.host || "http://localhost:3001") + "?tenant=" + (config.tenantId || "");
  iframe.style.cssText = "position:fixed;bottom:0;right:0;width:100px;height:100px;border:none;z-index:99999;background:transparent;";
  iframe.allow = "microphone";
  document.body.appendChild(iframe);

  window.addEventListener("message", function(e) {
    if (e.data.type === "voxagent:resize") {
      iframe.style.width = e.data.width + "px";
      iframe.style.height = e.data.height + "px";
    }
  });
})();
