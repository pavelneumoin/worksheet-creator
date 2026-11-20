"use strict";
// Local, hand-drawn interface symbols. One optical size and stroke throughout.
// Keep mathematical expressions in KaTeX; these SVGs only describe UI actions.
(() => {
  const ns = "http://www.w3.org/2000/svg";
  const path = d => ["path", {d}];
  const rect = (x, y, width, height, rx = 2) => ["rect", {x, y, width, height, rx}];
  const circle = (cx, cy, r, fill) => ["circle", {cx, cy, r, ...(fill ? {fill, stroke: "none"} : {})}];
  const fileOutline = path("M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6");
  const symbols = {
    filePlus: [fileOutline, path("M12 12v6m-3-3h6")],
    fileText: [fileOutline, path("M8 13h8m-8 4h5")],
    fileCheck: [fileOutline, path("m8.5 15 2.5 2.5 5-5")],
    library: [rect(3, 4, 5, 16, 1.5), rect(8, 4, 5, 16, 1.5), path("m15 5 3-1 4 15-3 1-4-15ZM5 8h1m4 0h1M5 16h1m4 0h1")],
    sharedLibrary: [path("M12 6.5C9.5 4.5 6 4 3 5v14c3-1 6.5-.5 9 1.5m0-14c2.5-2 6-2.5 9-1.5v14c-3-1-6.5-.5-9 1.5v-14Z"), path("M6 9h3m-3 4h3m6-4h3m-3 4h3")],
    classes: [circle(9, 8, 3), path("M3 20v-2a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v2M16 5a3 3 0 0 1 0 6m2 3a4 4 0 0 1 3 4v2")],
    calendar: [rect(3, 5, 18, 16), path("M7 3v4m10-4v4M3 10h18"), circle(8, 14, .9, "currentColor"), circle(12, 14, .9, "currentColor"), circle(16, 14, .9, "currentColor"), circle(8, 18, .9, "currentColor"), circle(12, 18, .9, "currentColor")],
    checklist: [path("M8 4H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"), rect(8, 2, 8, 4, 1.2), path("m7.5 11 1.5 1.5 2.5-2.5M14 12h3m-9.5 5h3m3.5 0h3")],
    chart: [path("M4 4v16h17M8 16v-5m5 5V7m5 9v-3")],
    school: [path("M4 21V8l8-5 8 5v13M3 21h18M9 21v-6h6v6M8 11v1M16 11v1"), circle(12, 8, 1.5)],
    graduationCap: [path("m2 8 10-5 10 5-10 5L2 8Zm4 2v7c4 2.7 8 2.7 12 0v-7m4-2v7")],
    inbox: [path("M5 4h14l3 11v5H2v-5L5 4Zm-3 11h6l2 3h4l2-3h6M12 7v6m-3-3 3 3 3-3")],
    settings: [path("M4 6h5m4 0h7M4 12h9m4 0h3M4 18h2m4 0h10"), circle(11, 6, 2), circle(15, 12, 2), circle(8, 18, 2)],
    photo: [rect(3, 3, 18, 18, 2.5), circle(8, 8, 1.5), path("m3 17 5-5 4 4 3-3 6 6")],
    camera: [path("M8 6 9.5 3h5L16 6h4a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4Z"), circle(12, 13, 4)],
    upload: [path("M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4")],
    download: [path("M12 3v13m-5-5 5 5 5-5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4")],
    save: [path("M5 3h12l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm3 0v6h8V3M7 21v-8h10v8")],
    share: [circle(18, 5, 3), circle(6, 12, 3), circle(18, 19, 3), path("m8.5 10.5 7-4m-7 7 7 4")],
    ellipsis: [circle(5, 12, 1.4, "currentColor"), circle(12, 12, 1.4, "currentColor"), circle(19, 12, 1.4, "currentColor")],
    star: [path("m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z")],
    play: [path("M8 5.5a.8.8 0 0 1 1.2-.7l10 6.5a.8.8 0 0 1 0 1.4l-10 6.5a.8.8 0 0 1-1.2-.7v-13Z")],
    chevronDown: [path("m6 9 6 6 6-6")],
    chevronRight: [path("m9 6 6 6-6 6")],
    chevronLeft: [path("m15 6-6 6 6 6")],
    arrowLeft: [path("M20 12H4m7-7-7 7 7 7")],
    arrowRight: [path("M4 12h16m-7-7 7 7-7 7")],
    plus: [path("M12 5v14M5 12h14")],
    minus: [path("M5 12h14")],
    check: [path("m5 12 4 4L19 6")],
    close: [path("m6 6 12 12M6 18 18 6")],
    trash: [path("M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7")],
    folder: [path("M3 7V5a2 2 0 0 1 2-2h5l3 4h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm0 0h10")],
    printer: [path("M7 8V3h10v5M7 17H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-3"), rect(7, 13, 10, 8, 0), circle(18, 11, .8, "currentColor")],
    copy: [rect(8, 8, 13, 13, 2.5), path("M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3")],
    math: [path("m4 10 7 8m0-8-7 8m11-11a2.5 2.5 0 1 1 4.8 1l-4.8 5h5")],
    atom: [["ellipse", {cx: 12, cy: 12, rx: 10, ry: 4}], ["ellipse", {cx: 12, cy: 12, rx: 10, ry: 4, transform: "rotate(60 12 12)"}], ["ellipse", {cx: 12, cy: 12, rx: 10, ry: 4, transform: "rotate(120 12 12)"}], circle(12, 12, 1.25, "currentColor")],
    flask: [path("M9 3h6m-5 0v6L4.8 18a2 2 0 0 0 1.7 3h11a2 2 0 0 0 1.7-3L14 9V3M7 14h10"), circle(11, 17, .8, "currentColor"), circle(14, 19, .6, "currentColor")],
    grid: [rect(3, 3, 18, 18), path("M9 3v18m6-18v18M3 9h18M3 15h18")],
    blank: [rect(4, 3, 16, 18)],
    lines: [path("M5 6h14M5 12h14M5 18h9")],
    search: [circle(10.5, 10.5, 6.5), path("m16 16 5 5")],
    filter: [path("M4 6h16M7 12h10M10 18h4")],
    message: [path("M5 3h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-6 4V5a2 2 0 0 1 2-2Zm2 5h10M7 12h7")],
    layers: [path("m3 7 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 17l9 5 9-5")],
    layout: [rect(3, 3, 18, 18), path("M3 9h18M10 9v12")],
    columns: [rect(3, 3, 7, 18), rect(14, 3, 7, 18)],
    text: [path("M4 5h16M12 5v15M8 20h8")],
    rotate: [path("M20 7V2l-4 4a8 8 0 1 0 4.6 9M20 7h-5")],
    logout: [path("M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5m5-14 5 5-5 5m-6-5h11")],
  };

  function svgFromShapes(shapes, {size = 20, className = ""} = {}) {
    const svg = document.createElementNS(ns, "svg");
    const dimension = Number.isFinite(Number(size)) && Number(size) > 0 ? Number(size) : 20;
    const attrs = {viewBox: "0 0 24 24", width: dimension, height: dimension, fill: "none", stroke: "currentColor", "stroke-width": 1.75, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: `listok-icon${className ? " " + className : ""}`};
    for (const [key, value] of Object.entries(attrs)) svg.setAttribute(key, String(value));
    for (const [tag, properties] of shapes) {
      const shape = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(properties)) shape.setAttribute(key, String(value));
      svg.append(shape);
    }
    return svg;
  }

  window.listokIcon = (name, options) => {
    if (!Object.prototype.hasOwnProperty.call(symbols, name)) throw new RangeError(`Unknown ListOK icon: ${name}`);
    return svgFromShapes(symbols[name], options);
  };
  window.listokPathIcon = (d, options) => svgFromShapes([path(d)], options);
})();
