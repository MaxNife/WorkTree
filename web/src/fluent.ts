// Register only the Fluent web components our wrappers use. Imported by main.ts, never by components,
// so unit tests run without custom-element registration.
import '@fluentui/web-components/button/define.js'
import '@fluentui/web-components/checkbox/define.js'
import '@fluentui/web-components/dialog/define.js'
import '@fluentui/web-components/dialog-body/define.js'
import '@fluentui/web-components/dropdown/define.js'
import '@fluentui/web-components/listbox/define.js'
import '@fluentui/web-components/option/define.js'
import '@fluentui/web-components/switch/define.js'
import '@fluentui/web-components/text-input/define.js'
import '@fluentui/web-components/textarea/define.js'
