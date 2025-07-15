import '@testing-library/jest-dom';
// import { render, screen } from '@testing-library/react';
// import { ReduxIntlProviders } from '../../../utils/testWithIntl';
// import { ProjectsMap } from '../projectsMap';

jest.mock('maplibre-gl/dist/maplibre-gl', () => ({
  GeolocateControl: jest.fn(),
  AttributionControl: jest.fn(),
  Map: jest.fn().mockImplementation(() => ({
    addControl: jest.fn(),
    addSource: jest.fn(),
    getSource: jest.fn(),
    on: jest.fn(),
    off: jest.fn(),
    remove: jest.fn(),
  })),
  addControl: jest.fn(),
  NavigationControl: jest.fn(),
  supported: jest.fn(),
  getRTLTextPluginStatus: jest.fn(),
}));

// test('displays WebGL not supported message', () => {
//   render(
//     <ReduxIntlProviders>
//       <ProjectsMap state={{ mapResults: null }} />
//     </ReduxIntlProviders>,
//   );
//   expect(
//     screen.getByRole('heading', {
//       name: 'WebGL Context Not Found',
//     }),
//   ).toBeInTheDocument();
// });
