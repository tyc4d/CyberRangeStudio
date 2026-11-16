// Colours used inside SVG graph canvases, where CSS variables cannot reach (edge markers). Keep in sync with theme.css.
export const EDGE = "#4ea6b3";     // a designed dependency / a planned connection (selected lines turn accent via CSS)
export const ROUTE = "#3bf4ff";
export const BARRIER = "#ff5666";  // a path that must stay blocked
export const TEMPORAL = "#6b7c8b"; // order only
export const MEMBER = "#2b3c4b";   // host-to-network membership
export const GRID = "#14212c";
export const CANVAS = "#070b11";
export const LABEL = "#8394a4";

// Topology view (X-Team look): deep navy canvas, blue/purple accents, light-grey wires. Keep in sync with .topo in theme.css.
export const TOPO_CANVAS = "#141a33";
export const TOPO_GRID = "#232b4f";
export const TOPO_WIRE = "#a9b0c4";  // gateway-to-zone and secondary-membership links
export const TOPO_LINK = "#8f8cff";  // a planned host-to-host connection
