from functools import partial
from tqdm import tqdm

import multiprocessing as mp
import pandas as pd
import geopandas as gpd
import numpy as np

idx = pd.IndexSlice

def cartesian(s1, s2):
    """Cartesian product of two pd.Series"""
    return pd.DataFrame(np.outer(s1, s2), index=s1.index, columns=s2.index)


def reverse(dictionary):
    """reverses a keys and values of a dictionary"""
    return {v: k for k, v in dictionary.items()}

non_EU = ["NO", "CH", "ME", "MK", "RS", "BA", "AL"]

idees_rename = {"GR": "EL", "GB": "UK"}

eu28 = [
    "FR",
    "DE",
    "GB",
    "IT",
    "ES",
    "PL",
    "SE",
    "NL",
    "BE",
    "FI",
    "CZ",
    "DK",
    "PT",
    "RO",
    "AT",
    "BG",
    "EE",
    "GR",
    "LV",
    "HU",
    "IE",
    "SK",
    "LT",
    "HR",
    "LU",
    "SI",
] + ["CY", "MT"]

eu28_eea = eu28.copy()
eu28_eea.remove("GB")
eu28_eea.append("UK")


to_ipcc = {
    "electricity": "1.A.1.a - Public Electricity and Heat Production",
    "residential non-elec": "1.A.4.b - Residential",
    "services non-elec": "1.A.4.a - Commercial/Institutional",
    "rail non-elec": "1.A.3.c - Railways",
    "road non-elec": "1.A.3.b - Road Transportation",
    "domestic navigation": "1.A.3.d - Domestic Navigation",
    "international navigation": "1.D.1.b - International Navigation",
    "domestic aviation": "1.A.3.a - Domestic Aviation",
    "international aviation": "1.D.1.a - International Aviation",
    "total energy": "1 - Energy",
    "industrial processes": "2 - Industrial Processes and Product Use",
    "agriculture": "3 - Agriculture",
    "agriculture, forestry and fishing": '1.A.4.c - Agriculture/Forestry/Fishing',
    "LULUCF": "4 - Land Use, Land-Use Change and Forestry",
    "waste management": "5 - Waste management",
    "other": "6 - Other Sector",
    "indirect": "ind_CO2 - Indirect CO2",
    "total wL": "Total (with LULUCF)",
    "total woL": "Total (without LULUCF)",
}


def eurostat_per_country(country):
    
    country_fn = idees_rename.get(country, country)
    fn = snakemake.input.eurostat + f"/{country_fn}-Energy-balance-sheets-June-2021-edition.xlsb"

    df = pd.read_excel(
        fn,
        sheet_name=None,
        skiprows=4,
        index_col=list(range(3)),
        na_values=["+", "-", "=", "Z", ":"],
    )

    df.pop("Cover")

    return pd.concat(df)


def build_eurostat(countries, year=None):
    """Return multi-index for all countries' energy data in TWh/a."""

    nprocesses = snakemake.threads
    tqdm_kwargs = dict(ascii=False, unit=' country', total=len(countries),
                    desc='Build from eurostat database')
    with mp.Pool(processes=nprocesses) as pool:
        dfs = list(tqdm(pool.imap(eurostat_per_country, countries), **tqdm_kwargs))

    index_names = ['country', 'year', 'lvl1', 'lvl2', 'lvl3']
    df = pd.concat(dfs, keys=countries, names=index_names)

    df.dropna(how='all', axis=0, inplace=True)
    df.dropna(how='all', axis=1, inplace=True)
    df = df[df.index.get_level_values('lvl1') != 'ktoe']

    i = df.index.to_frame(index=False)
    i.loc[i.lvl2 == 'Primary production', ['lvl1', 'lvl3']] = 'Main'
    i.loc[i.lvl2 == 'Gross electricity production', 'lvl1'] = "Gross production"
    i.ffill(inplace=True)
    df.index = pd.MultiIndex.from_frame(i)

    df.drop(list(range(1990, 2020)), axis=1, inplace=True)
    df.drop("Unnamed: 7", axis=1, inplace=True)
    df.fillna(0., inplace=True)

    # convert ktoe/a to TWh/a
    df *= 11.63 / 1e3

    if year:
        df = df.xs(str(year), level='year')

    return df


def build_swiss(year=None):
    """Return a pd.Series of Swiss energy data in TWh/a"""

    fn = snakemake.input.swiss

    df = pd.read_csv(fn, index_col=[0,1]).loc["CH"]

    if year:
        df = df[str(year)]

    # convert PJ/a to TWh/a
    df /= 3.6

    return df


def idees_per_country(country):

    base_dir = snakemake.input.idees

    ct_totals = {}

    ct_idees = idees_rename.get(country, country)
    fn_residential = f"{base_dir}/JRC-IDEES-2015_Residential_{ct_idees}.xlsx"
    fn_tertiary = f"{base_dir}/JRC-IDEES-2015_Tertiary_{ct_idees}.xlsx"
    fn_transport = f"{base_dir}/JRC-IDEES-2015_Transport_{ct_idees}.xlsx"

    # residential

    df = pd.read_excel(fn_residential, "RES_hh_fec", index_col=0)

    ct_totals["total residential space"] = df.loc["Space heating"]

    rows = ["Advanced electric heating", "Conventional electric heating"]
    ct_totals["electricity residential space"] = df.loc[rows].sum()

    ct_totals["total residential water"] = df.loc["Water heating"]

    assert df.index[23] == "Electricity"
    ct_totals["electricity residential water"] = df.iloc[23]

    ct_totals["total residential cooking"] = df.loc["Cooking"]

    assert df.index[30] == "Electricity"
    ct_totals["electricity residential cooking"] = df.iloc[30]

    df = pd.read_excel(fn_residential, "RES_summary", index_col=0)

    row = "Energy consumption by fuel - Eurostat structure (ktoe)"
    ct_totals["total residential"] = df.loc[row]

    assert df.index[47] == "Electricity"
    ct_totals["electricity residential"] = df.iloc[47]

    assert df.index[46] == "Derived heat"
    ct_totals["derived heat residential"] = df.iloc[46]

    assert df.index[50] == 'Thermal uses'
    ct_totals["thermal uses residential"] = df.iloc[50]

    # services

    df = pd.read_excel(fn_tertiary, "SER_hh_fec", index_col=0)

    ct_totals["total services space"] = df.loc["Space heating"]

    rows = ["Advanced electric heating", "Conventional electric heating"]
    ct_totals["electricity services space"] = df.loc[rows].sum()

    ct_totals["total services water"] = df.loc["Hot water"]

    assert df.index[24] == "Electricity"
    ct_totals["electricity services water"] = df.iloc[24]

    ct_totals["total services cooking"] = df.loc["Catering"]

    assert df.index[31] == "Electricity"
    ct_totals["electricity services cooking"] = df.iloc[31]

    df = pd.read_excel(fn_tertiary, "SER_summary", index_col=0)

    row = "Energy consumption by fuel - Eurostat structure (ktoe)"
    ct_totals["total services"] = df.loc[row]

    assert df.index[50] == "Electricity"
    ct_totals["electricity services"] = df.iloc[50]

    assert df.index[49] == "Derived heat"
    ct_totals["derived heat services"] = df.iloc[49]

    assert df.index[53] == 'Thermal uses'
    ct_totals["thermal uses services"] = df.iloc[53]

    # agriculture, forestry and fishing

    start = "Detailed split of energy consumption (ktoe)"
    end = "Market shares of energy uses (%)"

    df = pd.read_excel(fn_tertiary, "AGR_fec", index_col=0).loc[start:end]

    rows = [
        "Lighting",
        "Ventilation",
        "Specific electricity uses",
        "Pumping devices (electric)"
    ]
    ct_totals["total agriculture electricity"] = df.loc[rows].sum()

    rows = ["Specific heat uses", "Low enthalpy heat"]
    ct_totals["total agriculture heat"] = df.loc[rows].sum()

    rows = [
        "Motor drives",
        "Farming machine drives (diesel oil incl. biofuels)",
        "Pumping devices (diesel oil incl. biofuels)",
    ]
    ct_totals["total agriculture machinery"] = df.loc[rows].sum()

    row = "Agriculture, forestry and fishing"
    ct_totals["total agriculture"] = df.loc[row]

    # transport

    df = pd.read_excel(fn_transport, "TrRoad_ene", index_col=0)

    ct_totals["total road"] = df.loc["by fuel (EUROSTAT DATA)"]

    ct_totals["electricity road"] = df.loc["Electricity"]

    ct_totals["total two-wheel"] = df.loc["Powered 2-wheelers (Gasoline)"]

    assert df.index[19] == "Passenger cars"
    ct_totals["total passenger cars"] = df.iloc[19]

    assert df.index[30] == "Battery electric vehicles"
    ct_totals["electricity passenger cars"] = df.iloc[30]

    assert df.index[31] == "Motor coaches, buses and trolley buses"
    ct_totals["total other road passenger"] = df.iloc[31]

    assert df.index[39] == "Battery electric vehicles"
    ct_totals["electricity other road passenger"] = df.iloc[39]

    assert df.index[41] == "Light duty vehicles"
    ct_totals["total light duty road freight"] = df.iloc[41]

    assert df.index[49] == "Battery electric vehicles"
    ct_totals["electricity light duty road freight"] = df.iloc[49]

    row = "Heavy duty vehicles (Diesel oil incl. biofuels)"
    ct_totals["total heavy duty road freight"] = df.loc[row]

    assert df.index[61] == "Passenger cars"
    ct_totals["passenger car efficiency"] = df.iloc[61]

    df = pd.read_excel(fn_transport, "TrRail_ene", index_col=0)

    ct_totals["total rail"] = df.loc["by fuel (EUROSTAT DATA)"]

    ct_totals["electricity rail"] = df.loc["Electricity"]

    assert df.index[15] == "Passenger transport"
    ct_totals["total rail passenger"] = df.iloc[15]

    assert df.index[16] == "Metro and tram, urban light rail"
    assert df.index[19] == "Electric"
    assert df.index[20] == "High speed passenger trains"
    ct_totals["electricity rail passenger"] = df.iloc[[16, 19, 20]].sum()

    assert df.index[21] == "Freight transport"
    ct_totals["total rail freight"] = df.iloc[21]

    assert df.index[23] == "Electric"
    ct_totals["electricity rail freight"] = df.iloc[23]

    df = pd.read_excel(fn_transport, "TrAvia_ene", index_col=0)

    assert df.index[6] == "Passenger transport"
    ct_totals["total aviation passenger"] = df.iloc[6]

    assert df.index[10] == "Freight transport"
    ct_totals["total aviation freight"] = df.iloc[10]

    assert df.index[7] == "Domestic"
    ct_totals["total domestic aviation passenger"] = df.iloc[7]

    assert df.index[8] == "International - Intra-EU"
    assert df.index[9] == "International - Extra-EU"
    ct_totals["total international aviation passenger"] = df.iloc[[8,9]].sum()

    assert df.index[11] == "Domestic and International - Intra-EU"
    ct_totals["total domestic aviation freight"] = df.iloc[11]

    assert df.index[12] == "International - Extra-EU"
    ct_totals["total international aviation freight"] = df.iloc[12]

    ct_totals["total domestic aviation"] = ct_totals["total domestic aviation freight"] \
                                        + ct_totals["total domestic aviation passenger"]

    ct_totals["total international aviation"] = ct_totals["total international aviation freight"] \
                                            + ct_totals["total international aviation passenger"]

    df = pd.read_excel(fn_transport, "TrNavi_ene", index_col=0)

    # coastal and inland
    ct_totals["total domestic navigation"] = df.loc["by fuel (EUROSTAT DATA)"]

    df = pd.read_excel(fn_transport, "TrRoad_act", index_col=0)

    assert df.index[85] == "Passenger cars"
    ct_totals["passenger cars"] = df.iloc[85]

    return pd.DataFrame(ct_totals)


def build_idees(countries, year=None):

    nprocesses = snakemake.threads
    tqdm_kwargs = dict(ascii=False, unit=' country', total=len(countries),
                       desc='Build from IDEES database')
    with mp.Pool(processes=nprocesses) as pool:
        dfs = list(tqdm(pool.imap(idees_per_country, countries), **tqdm_kwargs))

    df = pd.concat(dfs, keys=countries, names=['country', 'year'])

    # convert ktoe to TWh
    exclude = df.columns.str.fullmatch("passenger cars")
    df.loc[:,~exclude] *= 11.63 / 1e3

    # convert TWh/100km to kWh/km
    df["passenger car efficiency"] *= 10

    # district heating share
    subset = ["derived heat residential", "derived heat services"]
    district_heat = df[subset].sum(axis=1)
    subset = ["thermal uses residential", "thermal uses services"]
    total_heat = df[subset].sum(axis=1)
    df["district heat share"] = district_heat.div(total_heat)

    if year:
        df = df.xs(int(year), level='year')

    return df


def build_energy_totals(countries, eurostat, swiss, idees):

    eurostat_fuels = dict(
        electricity="Electricity",
        total="Total"
    )

    eurostat_sectors = dict(
        residential="Households",
        services="Commercial & public services",
        road="Road",
        rail="Rail"
    )

    to_drop = ["passenger cars", "passenger car efficiency"]
    df = idees.reindex(countries).drop(to_drop, axis=1)

    eurostat_countries = eurostat.index.levels[0]
    in_eurostat = df.index.intersection(eurostat_countries)

    # add international navigation

    slicer = idx[in_eurostat, :, "International maritime bunkers", :]
    fill_values = eurostat.loc[slicer, "Total"].groupby(level=0).sum()
    df.loc[in_eurostat, "total international navigation"] = fill_values

    # add swiss energy data

    df.loc["CH"] = swiss

    # get values for missing countries based on Eurostat EnergyBalances
    # divide cooking/space/water according to averages in EU28

    missing = df.index[df["total residential"].isna()]
    to_fill = missing.intersection(eurostat_countries)
    uses = ["space", "cooking", "water"]

    for sector in ["residential", "services", "road", "rail"]:

        # fuel use

        for fuel in ["electricity", "total"]:
            slicer = idx[to_fill, :, :, eurostat_sectors[sector]]
            fill_values = eurostat.loc[slicer, eurostat_fuels[fuel]].groupby(level=0).sum()
            df.loc[to_fill, f"{fuel} {sector}"] = fill_values

    for sector in ["residential", "services"]:

        # electric use

        for use in uses:
            fuel_use = df[f"electricity {sector} {use}"]
            fuel = df[f"electricity {sector}"]
            avg = fuel_use.div(fuel).mean()
            print(f"{sector}: average fraction of electricity for {use} is {avg:.3f}")
            df.loc[to_fill, f"electricity {sector} {use}"] = avg * df.loc[to_fill, f"electricity {sector}"]

        # non-electric use

        for use in uses:
            nonelectric_use = df[f"total {sector} {use}"] - df[f"electricity {sector} {use}"]
            nonelectric = df[f"total {sector}"] - df[f"electricity {sector}"]
            avg = nonelectric_use.div(nonelectric).mean()
            print(f"{sector}: average fraction of non-electric for {use} is {avg:.3f}")
            electric_use = df.loc[to_fill, f"electricity {sector} {use}"]
            nonelectric = df.loc[to_fill, f"total {sector}"] - df.loc[to_fill, f"electricity {sector}"]
            df.loc[to_fill, f"total {sector} {use}"] = electric_use + avg * nonelectric

    # Fix Norway space and water heating fractions
    # http://www.ssb.no/en/energi-og-industri/statistikker/husenergi/hvert-3-aar/2014-07-14
    # The main heating source for about 73 per cent of the households is based on electricity
    # => 26% is non-electric
    elec_fraction = 0.73

    no_norway = df.drop("NO")

    for sector in ["residential", "services"]:

        # assume non-electric is heating
        nonelectric = df.loc["NO", f"total {sector}"] - df.loc["NO", f"electricity {sector}"]
        total_heating = nonelectric / (1 - elec_fraction)

        for use in uses:
            nonelectric_use = no_norway[f"total {sector} {use}"] - no_norway[f"electricity {sector} {use}"]
            nonelectric = no_norway[f"total {sector}"] - no_norway[f"electricity {sector}"]
            fraction = nonelectric_use.div(nonelectric).mean()
            df.loc["NO", f"total {sector} {use}"] = total_heating * fraction
            df.loc["NO", f"electricity {sector} {use}"] = total_heating * fraction * elec_fraction

    # Missing aviation

    slicer = idx[to_fill, :, :, "Domestic aviation"]
    fill_values = eurostat.loc[slicer, "Total"].groupby(level=0).sum()
    df.loc[to_fill, "total domestic aviation"] = fill_values

    slicer = idx[to_fill, :, "International aviation", :]
    fill_values = eurostat.loc[slicer, "Total"].groupby(level=0).sum()
    df.loc[to_fill, "total international aviation"] = fill_values

    # missing domestic navigation

    slicer = idx[to_fill, :, :, "Domestic navigation"]
    fill_values = eurostat.loc[slicer, "Total"].groupby(level=0).sum()
    df.loc[to_fill, "total domestic navigation"] = fill_values

    # split road traffic for non-IDEES
    missing = df.index[df["total passenger cars"].isna()]
    for fuel in ["total", "electricity"]:
        selection = [
            f"{fuel} passenger cars",
            f"{fuel} other road passenger",
            f"{fuel} light duty road freight",
        ]
        if fuel == "total":
            selection.extend([
                f"{fuel} two-wheel",
                f"{fuel} heavy duty road freight"
            ])
        road = df[selection].sum()
        road_fraction = road / road.sum()
        fill_values = cartesian(df.loc[missing, f"{fuel} road"], road_fraction)
        df.loc[missing, road_fraction.index] = fill_values

    # split rail traffic for non-IDEES
    missing = df.index[df["total rail passenger"].isna()]
    for fuel in ["total", "electricity"]:
        selection = [f"{fuel} rail passenger", f"{fuel} rail freight"]
        rail = df[selection].sum()
        rail_fraction = rail / rail.sum()
        fill_values = cartesian(df.loc[missing, f"{fuel} rail"], rail_fraction)
        df.loc[missing, rail_fraction.index] = fill_values

    # split aviation traffic for non-IDEES
    missing = df.index[df["total domestic aviation passenger"].isna()]
    for destination in ["domestic", "international"]:
        selection = [
            f"total {destination} aviation passenger",
            f"total {destination} aviation freight",
        ]
        aviation = df[selection].sum()
        aviation_fraction = aviation / aviation.sum()
        fill_values = cartesian(df.loc[missing, f"total {destination} aviation"], aviation_fraction)
        df.loc[missing, aviation_fraction.index] = fill_values

    for purpose in ["passenger", "freight"]:
        attrs = [f"total domestic aviation {purpose}", f"total international aviation {purpose}"]
        df.loc[missing, f"total aviation {purpose}"] = df.loc[missing, attrs].sum(axis=1)

    if "BA" in df.index:
        # fill missing data for BA (services and road energy data)
        # proportional to RS with ratio of total residential demand
        missing = df.loc["BA"] == 0.0
        ratio = df.at["BA", "total residential"] / df.at["RS", "total residential"]
        df.loc['BA', missing] = ratio * df.loc["RS", missing]

    # Missing district heating share
    dh_share = pd.read_csv(snakemake.input.district_heat_share,
                           index_col=0, usecols=[0, 1])
    # make conservative assumption and take minimum from both data sets
    df["district heat share"] = (pd.concat([df["district heat share"],
                                            dh_share.reindex(index=df.index)/100],
                                           axis=1).min(axis=1))

    return df


def build_eea_co2(year=1990):

    # https://www.eea.europa.eu/data-and-maps/data/national-emissions-reported-to-the-unfccc-and-to-the-eu-greenhouse-gas-monitoring-mechanism-16
    # downloaded 201228 (modified by EEA last on 201221)
    df = pd.read_csv(snakemake.input.co2, encoding="latin-1")

    df.replace(dict(Year="1985-1987"), 1986, inplace=True)
    df.Year = df.Year.astype(int)
    index_col = ["Country_code", "Pollutant_name", "Year", "Sector_name"]
    df = df.set_index(index_col).sort_index()

    emissions_scope = snakemake.config["energy"]["emissions"]

    cts = ["CH", "EUA", "NO"] + eu28_eea

    slicer = idx[cts, emissions_scope, year, to_ipcc.values()]
    emissions = (
        df.loc[slicer, "emissions"]
        .unstack("Sector_name")
        .rename(columns=reverse(to_ipcc))
        .droplevel([1,2])
    )

    emissions.rename(index={"EUA": "EU28", "UK": "GB"}, inplace=True)

    to_subtract = [
        "electricity",
        "services non-elec",
        "residential non-elec",
        "road non-elec",
        "rail non-elec",
        "domestic aviation",
        "international aviation",
        "domestic navigation",
        "international navigation",
        "agriculture, forestry and fishing"
    ]
    emissions["industrial non-elec"] = emissions["total energy"] - emissions[to_subtract].sum(axis=1)

    emissions["agriculture"] += emissions["agriculture, forestry and fishing"]

    to_drop = ["total energy", "total wL", "total woL", "agriculture, forestry and fishing"]
    emissions.drop(columns=to_drop, inplace=True)

    # convert from Gg to Mt
    return emissions / 1e3


def build_eurostat_co2(countries, year=1990):

    eurostat = build_eurostat(countries, year)

    specific_emissions = pd.Series(index=eurostat.columns, dtype=float)

    # emissions in tCO2_equiv per MWh_th
    specific_emissions["Solid fuels"] = 0.36  # Approximates coal
    specific_emissions["Oil (total)"] = 0.285  # Average of distillate and residue
    specific_emissions["Gas"] = 0.2  # For natural gas

    # oil values from https://www.eia.gov/tools/faqs/faq.cfm?id=74&t=11
    # Distillate oil (No. 2)  0.276
    # Residual oil (No. 6)  0.298
    # https://www.eia.gov/electricity/annual/html/epa_a_03.html

    return eurostat.multiply(specific_emissions).sum(axis=1)


def build_co2_totals(countries, eea_co2, eurostat_co2):

    co2 = eea_co2.reindex(countries)

    for ct in countries.intersection(["BA", "RS", "AL", "ME", "MK"]):

        mappings = {
            "electricity": (ct, "+", "Conventional Thermal Power Stations", "of which From Coal"),
            "residential non-elec": (ct, "+", "+", "Residential"),
            "services non-elec": (ct, "+", "+", "Services"),
            "road non-elec": (ct, "+", "+", "Road"),
            "rail non-elec": (ct, "+", "+", "Rail"),
            "domestic navigation": (ct, "+", "+", "Domestic Navigation"),
            "international navigation": (ct, "-", "Bunkers"),
            "domestic aviation": (ct, "+", "+", "Domestic aviation"),
            "international aviation": (ct, "+", "+", "International aviation"),
            # does not include industrial process emissions or fuel processing/refining
            "industrial non-elec": (ct, "+", "Industry"),
            # does not include non-energy emissions
            "agriculture": (eurostat_co2.index.get_level_values(0) == ct) & eurostat_co2.index.isin(["Agriculture / Forestry", "Fishing"], level=3),
        }

        for i, mi in mappings.items():
            co2.at[ct, i] = eurostat_co2.loc[mi].sum()

    return co2


def build_transport_data(countries, population, idees):

    transport_data = pd.DataFrame(index=countries)

    # collect number of cars

    transport_data["number cars"] = idees["passenger cars"]

    # CH from http://ec.europa.eu/eurostat/statistics-explained/index.php/Passenger_cars_in_the_EU#Luxembourg_has_the_highest_number_of_passenger_cars_per_inhabitant
    transport_data.at["CH", "number cars"] = 4.136e6

    missing = transport_data.index[transport_data["number cars"].isna()]
    print(f"Missing data on cars from:\n{list(missing)}\nFilling gaps with averaged data.")

    cars_pp = transport_data["number cars"] / population
    transport_data.loc[missing, "number cars"] = cars_pp.mean() * population

    # collect average fuel efficiency in kWh/km

    transport_data["average fuel efficiency"] = idees["passenger car efficiency"]

    missing = transport_data.index[transport_data["average fuel efficiency"].isna()]
    print(f"Missing data on fuel efficiency from:\n{list(missing)}\nFilling gapswith averaged data.")

    fill_values = transport_data["average fuel efficiency"].mean()
    transport_data.loc[missing, "average fuel efficiency"] = fill_values

    return transport_data


if __name__ == "__main__":
    if 'snakemake' not in globals():
        from helper import mock_snakemake
        snakemake = mock_snakemake('build_energy_totals')

    config = snakemake.config["energy"]

    nuts3 = gpd.read_file(snakemake.input.nuts3_shapes).set_index("index")
    population = nuts3["pop"].groupby(nuts3.country).sum()

    countries = population.index
    idees_countries = countries.intersection(eu28)

    data_year = config["energy_totals_year"]
    eurostat = build_eurostat(countries.difference(['CH']), data_year)
    swiss = build_swiss(data_year)
    idees = build_idees(idees_countries, data_year)

    energy = build_energy_totals(countries, eurostat, swiss, idees)
    energy.to_csv(snakemake.output.energy_name)

    base_year_emissions = config["base_emissions_year"]
    eea_co2 = build_eea_co2(base_year_emissions)
    eurostat_co2 = build_eurostat_co2(countries, base_year_emissions)

    co2 = build_co2_totals(countries, eea_co2, eurostat_co2)
    co2.to_csv(snakemake.output.co2_name)

    transport = build_transport_data(countries, population, idees)
    transport.to_csv(snakemake.output.transport_name)
