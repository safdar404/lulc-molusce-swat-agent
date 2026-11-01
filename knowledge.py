"""Teaching knowledge from the PhD LULC-MOLUSCE-SWAT manual (30 practicals)."""
PRACTICALS = {
 1: ("Research design and hypotheses", "Conceptual model and research matrix", "Why is a future LULC map a scenario rather than a fact?"),
 2: ("QGIS project, CRS and data architecture", "Reproducible project structure, data dictionary, processing log", "Why can two rasters share a CRS but still fail MOLUSCE geometry checks?"),
 3: ("Satellite imagery acquisition", "Multi-date image inventory", "Why is mixing 10 m and 30 m maps risky for change detection?"),
 4: ("Image preprocessing", "Analysis-ready imagery, raw data untouched", "What happens if atmospheric correction is applied twice?"),
 5: ("Spectral indices", "NDVI/NDWI/NDBI layers", "Why can NDBI confuse bare soil and built-up land?"),
 6: ("Training and validation design", "Independent sample datasets", "Why does reusing training pixels for validation inflate accuracy?"),
 7: ("LULC classification", "LULC_YYYY.tif with stable class codes", "Why must class codes remain stable across years?"),
 8: ("Accuracy assessment", "Confusion matrix and class metrics per year", "Can high overall accuracy hide a poor rare class?"),
 9: ("LULC area statistics", "Area and change tables in hectares", "What denominator is used for percentage change?"),
 10: ("Transition mapping", "From-to transition raster and matrix", "What does the diagonal of a transition matrix represent?"),
 11: ("DEM and slope", "Terrain drivers on the model grid", "Why can slope constrain urban expansion?"),
 12: ("Distance drivers", "Road, river and urban proximity rasters", "Why must distance be computed in a projected CRS?"),
 13: ("Population and other drivers", "Aligned explanatory stack and driver hypothesis table", "What is temporal leakage?"),
 14: ("Raster alignment and MOLUSCE QA", "Geometry-matched input stack", "What is grid origin?"),
 15: ("MOLUSCE correlation", "Driver diagnostic table with retain/remove reasons", "Does correlation prove causation?"),
 16: ("MOLUSCE area changes", "Class statistics, transition matrix, change map", "Why independently verify MOLUSCE area totals?"),
 17: ("ANN transition potential", "Fitted ANN with parameter log", "What indicates overfitting in the curves?"),
 18: ("Cellular automata simulation", "Simulated LULC and certainty outputs", "Why can spatially coherent output still be wrong?"),
 19: ("Hindcasting and validation", "Validated hindcast and disagreement map", "Why is hindcasting stronger than fitting history?"),
 20: ("Future LULC scenarios", "BAU, conservation, rapid-urbanisation maps", "What makes a scenario reproducible?"),
 21: ("SWAT+ data preparation", "Input inventory and lookup tables", "Which inputs control spatial discretisation?"),
 22: ("Watershed delineation", "Watershed, streams, subbasins", "How does stream threshold affect subbasin count?"),
 23: ("Land use, soils and slope classes", "Validated lookup tables and slope bands", "What happens if a raster code has no lookup entry?"),
 24: ("HRU/LSU generation", "HRU/LSU table and summaries", "What is lost with aggressive HRU thresholds?"),
 25: ("Climate and management inputs", "Quality-controlled weather and management", "Why is a warm-up period needed?"),
 26: ("Initial SWAT+ simulation", "Uncalibrated hydrograph and water balance", "Why not calibrate a broken water balance?"),
 27: ("Sensitivity and calibration", "Sensitivity ranking and calibrated parameters", "What is equifinality?"),
 28: ("Independent validation", "Validation statistics with frozen parameters", "Why must parameters stay fixed during validation?"),
 29: ("Future LULC hydrological scenarios", "Scenario output database and change tables", "How do you isolate LULC from climate effects?"),
 30: ("Statistics, maps and thesis writing", "Figure/table package and methods appendix", "What belongs in Results versus Discussion?"),
}
FOLDERS = ["01_Raw_Data", "02_Preprocessed", "03_Classification", "04_Accuracy", "05_Drivers",
           "06_MOLUSCE", "07_SWAT", "08_Scenarios", "09_Statistics", "10_Thesis"]  # 01 and 10 are from the manual; the rest are suggested


def guide(query):
    q = str(query).strip().lower()
    if q.isdigit() and int(q) in PRACTICALS:
        n = int(q)
        t, d, v = PRACTICALS[n]
        return dict(practical=n, title=t, deliverable=d, viva_question=v)
    hits = [dict(practical=n, title=t, deliverable=d, viva_question=v)
            for n, (t, d, v) in PRACTICALS.items() if q in t.lower() or q in d.lower()]
    return dict(matches=hits[:8])
