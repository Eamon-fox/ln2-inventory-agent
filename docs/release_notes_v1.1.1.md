## What's Changed

### 🎨 UI & Design
- **Flat Design Modernization**: Apply modern flat design styling across all components (Phases 1-4)
- **Typography Improvements**: Increase overview typography scale and add centralized font size configuration
- **Visual Enhancements**: Tint table rows with grid color mapping, improve checkbox visibility
- **Icon System**: Refresh desktop controls with Lucide icon assets and cleaner context feedback
- **Interactive Components**: Replace view mode dropdown with flat toggle buttons, improve segmented buttons
- **AI Panel Polish**: Refine input styling, adjust button proportions, prevent text clipping

### ✨ Features
- **Audit Log Dialog**: Extract audit log to independent dialog window for better usability
- **Cell Line Hints**: Add guided cell-line hints to constrained pickers and options
- **System Notice**: Improve system notice rendering and display
- **Installer**: Update exe naming to include version number

### 🔧 Bug Fixes
- Fix validation: improve plan conflict detection and simplify UI
- Fix positioning: honor layout-aware slot IDs across staging
- Fix UI: prevent button text clipping, correct bridge attribute in audit dialog
- Remove unsupported CSS transition properties

### 🛠️ Refactoring
- Agent: consolidate overlapping tools into unified interfaces
- Positions: change positions list to single position field
- Operations: hard-cut operation notes before launch

### 📚 Documentation
- Rebrand app to SnowFox and refresh onboarding docs

### 🔧 Maintenance
- Improve .gitignore with comprehensive Python, PyInstaller, IDE, and testing patterns
- Bump version to 1.1.1
