#include "../src/App/Osu/OsuTimingAudioReference.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); } } while (false)
typedef OsuTimingAudioReference Ref;
static void near(double value, double expected) { CHECK(std::abs(value - expected) < 0.00000001); }

int main()
{
	for (double od : {0.0, 5.0, 10.0})
	{
		const Ref::Windows windows = {80 - 6 * od, 140 - 8 * od, 200 - 10 * od};
		for (double speed : {0.75, 1.0, 1.5, 2.3})
			for (double sign : {-1.0, 1.0})
				for (int band = 0; band <= 3; ++band)
				{
					const double edge = band == 0 ? 0 : band == 1 ? windows.hit300 : band == 2 ? windows.hit100 : windows.hit50;
					const auto r = Ref::calculate(17, speed, sign * band, windows);
					CHECK(r.valid); near(r.targetMapMS, sign * edge); near(r.targetMS, sign * edge / speed);
				}
	}
	const Ref::Windows od10 = {20, 60, 100};
	near(Ref::calculate(0, 1, 0.5, od10).targetMapMS, 10);
	near(Ref::calculate(0, 1, 1.5, od10).targetMapMS, 40);
	near(Ref::calculate(0, 1, -2.5, od10).targetMapMS, -80);
	near(Ref::calculate(0, 1, 1.5, {73.4, 131.2, 189}).targetMapMS, 102);
	// OD lock's current getters, not an independent lock of all three widths.
	near(Ref::calculate(0, 1.5, 2, {75, 133.333328, 191.666656}).targetMS, 133 / 1.5);
	near(Ref::calculate(0, .75, 3, {37.5, 83.333336, 129.166672}).targetMS, 172);
	const Ref::Windows od5 = {50, 100, 150};
	CHECK(35 / 1.5 - 50 / 1.5 < -10);
	CHECK(Ref::calculate(35, 1.5, 1, od5).deviationMS == -10);
	CHECK(Ref::calculate(-35, 1.5, -1, od5).deviationMS == 10);
	CHECK(Ref::calculate(5, 1, -0.1L, od5).deviationMS == 10);
	CHECK(Ref::calculate(45, 1, 1.1L, od5).deviationMS == -10);
	CHECK(Ref::calculate(9, 1.5, 1.1L, od10).deviationMS == -10);
	const volatile long double decimalTarget = 2.1L;
	CHECK(Ref::calculate(105, 1, decimalTarget, od5).deviationMS == 0);
	CHECK(Ref::calculate(-105, 1.5, -decimalTarget, od5).deviationMS == 0);
	const volatile long double thirdTarget = 0.3L;
	CHECK(Ref::calculate(15, 1, thirdTarget, od5).deviationMS == 0);
	CHECK(Ref::calculate(-15, 1, -thirdTarget, od5).deviationMS == 0);
	near(Ref::calculate(40, 1.5, .5, {80, 140, 200}).deviationMS, 0);
	const double nan = std::numeric_limits<double>::quiet_NaN();
	for (long error : {-120L, 0L, 120L})
		for (double speed : {.75, 1.0, 1.5})
		{
			const auto zero = Ref::calculate(error, speed, 0, {nan, nan, nan});
			CHECK(zero.valid && zero.deviationMS == static_cast<double>(error) / speed);
		}
	const Ref::Windows invalid[] = {{0, 100, 150}, {50, 50.9, 150}, {60, 50, 150}, {50, nan, 150}, {50, 100, std::numeric_limits<double>::infinity()}};
	for (Ref::Windows bad : invalid)
		CHECK(!Ref::calculate(0, 1, 1, bad).valid);
	CHECK(!Ref::calculate(0, 0, 1, od5).valid);
	CHECK(!Ref::calculate(0, 1, 3.01, od5).valid);
	CHECK(!Ref::calculate(0, 1, nan, od5).valid);
	long edge = 0;
	CHECK(Ref::truncateWindow(50.99, edge) && edge == 50);
	CHECK(!Ref::truncateWindow(-1, edge));
	CHECK(!Ref::truncateWindow(-static_cast<double>(LONG_MIN), edge));
	std::puts("PASS: timing reference signs, judgement anchors, rates/OD lock, raw-first boundaries and invalid geometry");
}
