// jsdom has <dialog> but not its methods. This is the small part of them UDialog uses: showModal()
// and show() open it, close() closes it and fires `close`, as a browser does.
if (typeof HTMLDialogElement !== 'undefined' && typeof HTMLDialogElement.prototype.showModal !== 'function') {
  Object.assign(HTMLDialogElement.prototype, {
    show(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    },
    showModal(this: HTMLDialogElement) {
      this.setAttribute('open', '')
    },
    close(this: HTMLDialogElement) {
      if (!this.hasAttribute('open')) return
      this.removeAttribute('open')
      this.dispatchEvent(new Event('close'))
    },
  })
}
