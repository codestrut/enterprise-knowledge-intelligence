export function navigate(path: string) {
  const navigationEvent = new CustomEvent("ekip:before-navigate", { detail: path, cancelable: true });
  window.dispatchEvent(navigationEvent);
  if (navigationEvent.defaultPrevented) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new Event("ekip:navigate"));
}

export function handleInternalLink(event: React.MouseEvent<HTMLAnchorElement>, href: string) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(href);
}
