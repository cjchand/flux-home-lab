// The tag checkbox submits its enclosing form immediately.
document.querySelectorAll("form.tagform").forEach((form) => {
  const chk = form.querySelector("input[type=checkbox]");
  if (chk) chk.addEventListener("change", () => form.submit());
});
