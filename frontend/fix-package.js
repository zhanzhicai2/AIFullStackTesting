const fs = require('fs');
const path = './node_modules/click-to-react-component/package.json';
try {
  const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
  if (!pkg.exports) {
    pkg.exports = {
      '.': {
        'import': './index.js',
        'require': './index.js'
      }
    };
    fs.writeFileSync(path, JSON.stringify(pkg, null, 2));
    console.log('Fixed click-to-react-component package.json');
  } else {
    console.log('Package already has exports field');
  }
} catch (error) {
  console.error('Error fixing package:', error.message);
}
