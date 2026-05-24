// Test the template condition regex
const re = /states\(\s*['"]([^'"]+)['"]\s*\)\s*(==|!=|>|<|>=|<=)\s*\\?["']?([^"'\\}\s]+)/;
const reIs = /is_state\(\s*['"]([^'"]+)['"],\s*['"]([^'"]+)['"]\)/;

// These are the actual value_template strings as they appear in the JSON config
// (HA parses YAML escapes, so \" becomes ")
const vt1 = "{{ states('sensor.house_energy_management_mode') == \"GRID_ONLY\" }}";
const vt2 = '{{ states("sensor.house_energy_management_mode") == "BALANCE"}} ';
const vt3 = "{{ is_state('sensor.pv_power', 'on') }}";

console.log("vt1:", JSON.stringify(vt1));
console.log("match1:", re.exec(vt1));
console.log();
console.log("vt2:", JSON.stringify(vt2));
console.log("match2:", re.exec(vt2));
console.log();
console.log("vt3:", JSON.stringify(vt3));
console.log("match3 (is_state):", reIs.exec(vt3));
