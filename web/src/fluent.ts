// Register only the Fluent web components our wrappers use. Imported by main.ts, never by components,
// so unit tests run without custom-element registration.
import '@fluentui/web-components/button/define.js'
import '@fluentui/web-components/checkbox/define.js'
import '@fluentui/web-components/switch/define.js'
import '@fluentui/web-components/text-input/define.js'
