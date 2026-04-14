import React, { memo } from 'react'
import {
  ComposableMap,
  Geographies,
  Geography,
  Annotation,
} from 'react-simple-maps'

const GEO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json'

// Normalise country names that differ between the model output and TopoJSON
const NAME_MAP = {
  'Czech Republic': 'Czechia',
  'UK': 'United Kingdom',
  'Holland': 'Netherlands',
  'South Korea': 'South Korea',
  'USA': 'United States of America',
  'US': 'United States of America',
}

// Approximate label anchor points for European countries
const LABEL_COORDS = {
  'Germany':         [10.4, 51.2],
  'France':          [2.3,  46.6],
  'Netherlands':     [5.3,  52.4],
  'Belgium':         [4.5,  50.5],
  'Switzerland':     [8.2,  46.8],
  'Austria':         [14.6, 47.5],
  'Sweden':          [18.0, 59.3],
  'Norway':          [10.7, 60.5],
  'Denmark':         [10.2, 56.0],
  'Finland':         [25.7, 61.9],
  'Poland':          [19.1, 51.9],
  'Spain':           [-3.7, 40.4],
  'Italy':           [12.6, 42.8],
  'Portugal':        [-8.2, 39.4],
  'Ireland':         [-8.2, 53.1],
  'United Kingdom':  [-3.4, 55.4],
  'Czechia':         [15.5, 49.8],
  'Romania':         [24.9, 45.9],
  'Hungary':         [19.0, 47.2],
  'United States of America': [-100, 40],
}

function normalize(name) {
  return NAME_MAP[name] || name
}

const ServiceMap = memo(function ServiceMap({ serviceCountries = [], hqCountry = '' }) {
  const normalizedService = serviceCountries.map(normalize)
  const normalizedHq = normalize(hqCountry)

  const labelCountries = normalizedService.filter(c => LABEL_COORDS[c])

  return (
    <div className="w-full bg-[#0a2e1a] rounded-xl overflow-hidden" style={{ height: 320 }}>
      <ComposableMap
        projection="geoMercator"
        projectionConfig={{ center: [10, 52], scale: 580 }}
        style={{ width: '100%', height: '100%' }}
      >
        <Geographies geography={GEO_URL}>
          {({ geographies }) =>
            geographies.map(geo => {
              const name = geo.properties.name
              const isHq = name === normalizedHq
              const isService = normalizedService.includes(name)

              let fill = '#1a3a2a'
              if (isHq) fill = '#00E676'
              else if (isService) fill = '#00C853'

              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill={fill}
                  stroke="#0a2e1a"
                  strokeWidth={0.5}
                  style={{ default: { outline: 'none' }, hover: { outline: 'none' }, pressed: { outline: 'none' } }}
                />
              )
            })
          }
        </Geographies>

        {/* Country label annotations */}
        {labelCountries.map(country => {
          const coords = LABEL_COORDS[country]
          if (!coords) return null
          return (
            <Annotation
              key={country}
              subject={coords}
              dx={0}
              dy={0}
              connectorProps={{}}
            >
              <rect
                x={-30} y={-10}
                width={60} height={20}
                rx={4}
                fill="rgba(0,0,0,0.55)"
              />
              <text
                x={0} y={4}
                textAnchor="middle"
                fontSize={8}
                fill="#ffffff"
                style={{ fontFamily: 'sans-serif', fontWeight: 600, pointerEvents: 'none' }}
              >
                {country === normalizedHq ? `★ ${country}` : country}
              </text>
            </Annotation>
          )
        })}
      </ComposableMap>
    </div>
  )
})

export default ServiceMap
