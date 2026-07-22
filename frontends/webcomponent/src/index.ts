// Log build information when the module loads
console.log(
  '%c🎨 Vanna Web Components',
  'color: #4CAF50; font-weight: bold; font-size: 14px;'
);
console.log(
  `%c📦 Version: ${__BUILD_VERSION__}`,
  'color: #2196F3; font-weight: bold;'
);
console.log(
  `%c🕐 Built: ${__BUILD_TIME__}`,
  'color: #FF9800; font-weight: bold;'
);
console.log(
  '%c━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
  'color: #9E9E9E;'
);

export { EasyQ2SqlChat } from './components/easyq2sql-chat';
export { EasyQ2SqlMessage } from './components/easyq2sql-message';
export { EasyQ2SqlStatusBar } from './components/easyq2sql-status-bar';
export { EasyQ2SqlProgressTracker } from './components/easyq2sql-progress-tracker';
export { PlotlyChart } from './components/plotly-chart';

// Rich component system
export {
  ComponentRegistry,
  ComponentManager,
  CardComponentRenderer,
  TaskListComponentRenderer,
  ProgressBarComponentRenderer,
  NotificationComponentRenderer,
  StatusIndicatorComponentRenderer,
  TextComponentRenderer
} from './components/rich-component-system';

// Rich component styles are injected automatically by the ComponentManager
